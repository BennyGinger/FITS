"""Combined tables obey the same overwrite, bypass and retention choices as other results."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from fits_io import FitsIO

from fits.environment import constant as cst
from fits.gui.settings import SettingsAdapter
from fits.pipeline import start_pipeline
from fits.settings.loader import resolve_step_params
from fits.settings.models import SettingsModel
from fits.tasks.analysis.aggregate import save_master_analysis_table
from fits.tasks.common.artifact_results import complete_step_result, save_step_result
from fits.tasks.common.table_results import save_parquet
from fits.tasks.common.preparation import load_input_reader
from fits.workflows.artifacts.provenance import read_metadata, revision_payload
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.analysis import MEMBERSHIP_KEY
from fits.workflows.definitions.inputs import configured_profile
from fits.workflows.definitions.models import StepProfile
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState, save_experiment_state
from fits.workflows.experiments.exclusion import set_excluded
from test_experiment_exclusion import _series


def _measurements(label: str) -> pd.DataFrame:
    """
    Provide a minimal valid quantification result for real master aggregation.
    """
    return pd.DataFrame({'object_name': ['segmentation'], 'object_channel': [label],
                         'label': [1], 'frame': [1], 'intensity_mean': [10.0]})


def _run_with_stale_table(root: Path) -> tuple[SettingsAdapter, ExperimentState, Path]:
    """
    Create compatible real outputs with a quantification table referencing an older image.
    """
    state = _series(root)[0]
    source = state.artifact(cst.ARTI_IMG_RAW)
    assert source is not None
    reader = FitsIO.from_path(source)
    label = reader.channel_labels[0]
    adapter = SettingsAdapter()
    adapter.run_dir = str(root)
    adapter.user_name = 'Test'
    adapter.set_runtime_value('execution', 'batch')
    for step in cst.WORKFLOW_ORDER:
        adapter.set_step_enabled(step, step in (cst.StepName.BG_SUB, cst.StepName.SEGMENT, cst.StepName.EXTRACT))
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', [label])
    adapter.set_segment_channels([{'channel': label}])
    config = adapter.as_mapping()
    profile = configured_profile(REGISTRY[cst.StepName.BG_SUB].profile, config)
    settings = REGISTRY[cst.StepName.BG_SUB].model_validate(resolve_step_params(cst.StepName.BG_SUB, config[cst.StepName.BG_SUB]))
    state = state.with_metadata(step_name=cst.StepName.BG_SUB, created_by=profile.distribution,
                                exported_channel='all', channels_params=settings.to_payload_dict())
    state = save_step_result(reader, reader.get_array().array.astype(np.float32), reader.channel_labels, state, profile)
    image = state.artifact(cst.ARTI_IMG_BGSUB)
    assert image is not None
    reader = FitsIO.from_path(image)
    profile = configured_profile(REGISTRY[cst.StepName.SEGMENT].profile, config)
    state = save_step_result(reader, np.ones_like(reader.get_array().array, dtype=np.uint16), reader.channel_labels, state, profile)
    mask = state.artifact(cst.ARTI_SEG)
    assert mask is not None
    payload = reader.metadata.with_fitsio(artifact_type=cst.ARTI_QUANTI).new_revision([
        {'artifact_path': image.name, 'created_at': 'older image revision'},
        {'artifact_path': mask.name, 'created_at': read_metadata(mask).fits_io.created_at}])
    table = save_parquet(_measurements(label), state.workdir / cst.FITS_QUANTI_NAME, payload)
    state = state.with_complete_step(step_name=cst.StepName.EXTRACT, artifact_kind=cst.ARTI_QUANTI, artifact_path=table)
    save_experiment_state(state)
    master = save_master_analysis_table([state], root, artifact_kind=cst.ARTI_QUANTI, output_name=cst.MASTER_QUANTI_NAME)
    assert master is not None
    return adapter, state, master


def _mock_processing(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """
    Publish genuine revisions without running a segmentation model or numerical extraction.
    """
    processed: list[str] = []

    def process(settings: SettingsModel, state: ExperimentState, profile: StepProfile) -> list[ExperimentState]:
        """
        Reuse completed steps or write a new result with real input provenance.
        """
        existing = state.artifact(profile.output_artifact)
        if existing is not None and existing.is_file() and not settings.overwrite:
            return [state]
        processed.append(str(profile.step_name))
        reader = load_input_reader(state, profile)
        if profile.step_name == cst.StepName.EXTRACT:
            payload = revision_payload(reader, state, profile, export_channels=reader.channel_labels)
            output = save_parquet(_measurements(reader.channel_labels[0]), state.workdir / profile.output_name, payload)
            return [complete_step_result(state, profile, output)]
        array = reader.get_array().array
        pixels = np.ones_like(array, dtype=np.uint16) if profile.step_name == cst.StepName.SEGMENT else array.astype(np.float32) + 1
        return [save_step_result(reader, pixels, reader.channel_labels, state, profile)]

    for step in (cst.StepName.BG_SUB, cst.StepName.SEGMENT, cst.StepName.EXTRACT):
        monkeypatch.setitem(REGISTRY, step, replace(REGISTRY[step], item_runner=process))
    return processed


@pytest.mark.parametrize('engine', ['batch', 'conveyor'])
@pytest.mark.parametrize('decision', ['selected', 'rebuild', 'continue', 'bypass'])
def test_tables_follow_normal_artifact_choices(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch,
                                              engine: str,
                                              decision: str,
                                              ) -> None:
    """
    Retain stale tables byte-for-byte unless rebuilding their included analysis is selected.
    """
    adapter, state, master = _run_with_stale_table(tmp_path)
    adapter.set_runtime_value('execution', engine)
    adapter.set_field_value(cst.StepName.BG_SUB, 'overwrite', decision != 'continue')
    if decision == 'bypass':
        adapter.set_step_enabled(cst.StepName.SEGMENT, False)
        adapter.set_step_enabled(cst.StepName.EXTRACT, False)
    calls = _mock_processing(monkeypatch)
    files = [state.workdir / name for name in (cst.FITS_MASK_SEG, cst.FITS_QUANTI_NAME)] + [master]
    before = {path: path.read_bytes() for path in files}
    reviewed: list[Any] = []

    def choose(report: Any) -> str:
        """
        Choose the same action exposed by the review dialog for ordinary artifacts.
        """
        reviewed.append(report)
        assert report.outdated_masters == (master,)
        return decision

    start_pipeline(adapter.save_to_run_dir(), artifact_decision=choose, terminal_progress=False)
    assert bool(reviewed) == (decision != 'bypass')
    assert calls == ([] if decision == 'continue' else ['bg_sub', 'segment', 'extract'] if decision == 'rebuild' else ['bg_sub'])
    if decision == 'rebuild':
        assert master.read_bytes() != before[master]
    else:
        assert all(path.read_bytes() == previous for path, previous in before.items())
    report = inspect_run(tmp_path, adapter.as_mapping(), for_execution=False)
    assert bool(report.outdated_masters) == (decision != 'rebuild')
    if decision == 'bypass':
        assert not report.needs_decision
        assert any('extract' in warning for warning in report.warnings)


@pytest.mark.parametrize('decision', ['continue', 'selected', 'rebuild'])
def test_changed_membership_can_be_retained_or_rebuilt(tmp_path: Path, decision: str) -> None:
    """
    Let the user retain an outdated combined table even when all its experiments are excluded.
    """
    adapter, state, master = _run_with_stale_table(tmp_path)
    before = master.read_bytes()
    set_excluded(tmp_path, [state.workdir], True)
    start_pipeline(adapter.save_to_run_dir(), artifact_decision=lambda report: decision, terminal_progress=False)
    if decision != 'rebuild':
        assert master.read_bytes() == before
        assert inspect_run(tmp_path, adapter.as_mapping()).outdated_masters == (master,)
    else:
        assert not master.exists()


def test_overwriting_final_analysis_does_not_prompt_for_its_own_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Refresh a selected analysis and its combined output without an extra downstream decision.
    """
    adapter, _, master = _run_with_stale_table(tmp_path)
    table = pq.read_table(master)
    metadata = {**(table.schema.metadata or {}), MEMBERSHIP_KEY: b'[]'}
    pq.write_table(table.replace_schema_metadata(metadata), master)
    adapter.set_field_value(cst.StepName.EXTRACT, 'overwrite', True)
    processed = _mock_processing(monkeypatch)
    report = inspect_run(tmp_path, adapter.as_mapping())
    assert report.outdated_masters == (master,)
    assert not report.needs_decision
    start_pipeline(adapter.save_to_run_dir(),
                   artifact_decision=lambda report: pytest.fail('A selected final analysis can refresh its own master.'),
                   terminal_progress=False)
    assert processed == ['extract']
    assert not inspect_run(tmp_path, adapter.as_mapping(), for_execution=False).outdated_masters
