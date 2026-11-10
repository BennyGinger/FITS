"""Durable per-series exclusion across conversion, execution and aggregation."""

from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any

import numpy as np
import pandas as pd
import pytest
import tifffile
from scope_io import ScopeIO

from fits.environment import constant as cst
from fits.environment.paths import experiment_state_path
from fits.settings.models import ConvertSettings, SettingsModel
from fits.tasks.analysis.aggregate import save_master_analysis_table
from fits.tasks.convert import convert
from fits.workflows.checks.analysis import outdated_master_tables
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.compatibility import inspect_run_compatibility
from fits.workflows.checks.decisions import apply_decision
from fits.workflows.definitions.models import StepProfile
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState, discover_saved_states, load_experiment_state, save_experiment_state
from fits.workflows.experiments.assembly import assemble_experiment_states
from fits.workflows.experiments.exclusion import active_raw_files, selected_experiments, set_excluded
from fits.workflows.experiments.serialization import deserialize_experiment_state, serialize_experiment_state
from fits.workflows.file_management.rebuild import full_rebuild_scope
from fits.workflows.runtime.batch import run_batch_workflow
from fits.workflows.runtime.interactive.execution import PhaseExecutor
from fits.workflows.runtime.interactive.interaction import PipelineInteraction
from fits.workflows.runtime.progress import RunProgress, WorkflowStage
from fits.workflows.runtime.scheduler import run_workflow_scheduler


def _series(root: Path) -> list[ExperimentState]:
    """
    Convert a small acquisition into real, current-format series for integration checks.
    """
    raw = root / 'input.tif'
    tifffile.imwrite(raw, np.ones((8, 8), dtype=np.uint16), metadata={'axes': 'YX'})
    return convert(ConvertSettings(), ExperimentState.init(root, raw, run_dir=root),
                   REGISTRY[cst.StepName.CONVERT].profile,
                   )


@pytest.mark.parametrize('value,expected', [(None, False), (False, False), (True, True), ('true', False), (1, False)])
def test_only_explicit_true_excludes(tmp_path: Path, value: Any, expected: bool) -> None:
    """
    Keep missing, legacy and nonboolean tags active.
    """
    state = ExperimentState.init(tmp_path, tmp_path / 'input.nd2')
    payload = serialize_experiment_state(state)
    if value is None:
        payload.pop('excluded')
    else:
        payload['excluded'] = value
    loaded = ExperimentState(workdir=tmp_path, **deserialize_experiment_state(payload))
    assert loaded.excluded is expected


def test_selection_persistence_and_all_excluded_acquisition(tmp_path: Path) -> None:
    """
    Deduplicate overlapping folders and retain excluded states in discovery.
    """
    state = _series(tmp_path)[0]
    assert selected_experiments([state], [state.workdir.parent, state.workdir]) == [state]
    set_excluded(tmp_path, [state.workdir.parent, state.workdir], True)
    loaded = discover_saved_states(tmp_path)
    assert len(loaded) == 1 and loaded[0].excluded
    assert active_raw_files([state.original_image], loaded) == []
    assert full_rebuild_scope(loaded, {}) == {}
    assert assemble_experiment_states(tmp_path, [state.original_image],
                                      {'convert': {'enabled': True, 'params': {'overwrite': True}}}, 'Test') == []
    set_excluded(tmp_path, [state.workdir], False)
    assert not load_experiment_state(state.workdir).excluded


def test_conversion_rebuild_preserves_excluded_sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Rebuild an active sibling without touching the excluded series or its saved flag.
    """
    def split(source: ScopeIO) -> list[ScopeIO]:
        """
        Represent a two-series acquisition using the same small source pixels.
        """
        return [source, source]

    monkeypatch.setattr(ScopeIO, 'split_series', split)
    first, second = _series(tmp_path)
    set_excluded(tmp_path, [second.workdir], True)
    image = second.artifact(cst.ARTI_IMG_RAW)
    assert image is not None
    image_bytes = image.read_bytes()
    state_bytes = experiment_state_path(second.workdir).read_bytes()
    result = convert(ConvertSettings(overwrite=True),
                     ExperimentState.init(first.original_image.parent, first.original_image, run_dir=tmp_path),
                     REGISTRY[cst.StepName.CONVERT].profile,
                     )
    assert [state.workdir for state in result] == [first.workdir]
    assert image.read_bytes() == image_bytes
    assert experiment_state_path(second.workdir).read_bytes() == state_bytes
    assert load_experiment_state(second.workdir).excluded


@pytest.mark.parametrize('mode', ['batch', 'conveyor', 'interactive'])
def test_engines_filter_initial_states_and_produced_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """
    Never schedule an excluded initial experiment or an excluded branch emitted by conversion.
    """
    source = ExperimentState.init(tmp_path, tmp_path / 'input.nd2')
    active = replace(source, workdir=tmp_path / 'active')
    excluded = replace(source, workdir=tmp_path / 'excluded', excluded=True)
    calls: list[tuple[str, Path]] = []

    def runner(settings: SettingsModel, state: ExperimentState, profile: StepProfile) -> list[ExperimentState]:
        """
        Emit mixed conversion branches and record subsequent processing.
        """
        calls.append((str(profile.step_name), state.workdir))
        return [active, excluded] if profile.step_name == cst.StepName.CONVERT else [state]

    for step in (cst.StepName.CONVERT, cst.StepName.BG_SUB):
        monkeypatch.setitem(REGISTRY, step, replace(REGISTRY[step], item_runner=runner))
    config = {str(step): {'enabled': True, 'params': {}} for step in (cst.StepName.CONVERT, cst.StepName.BG_SUB)}
    if mode == 'batch':
        result = run_batch_workflow(config, [source, excluded], terminal_progress=False)
    elif mode == 'conveyor':
        result = run_workflow_scheduler(config, [source, excluded], terminal_progress=False)
    else:
        from fits.workflows.runtime.scheduler import resolve_runtime_steps
        progress = RunProgress()
        progress.add(source.experiment_id, {WorkflowStage.CONVERT})
        executor = PhaseExecutor(PipelineInteraction(lambda request: None, lambda: None), progress, Event())
        result = executor.run([source, excluded], tuple(resolve_runtime_steps(config)), WorkflowStage.CONVERT,
                              source.experiment_id,
                              )
    assert calls == [('convert', source.workdir), ('bg_sub', active.workdir)]
    assert result == [active]


def test_excluded_artifacts_do_not_block_execution_checks(tmp_path: Path) -> None:
    """
    Preserve inspectability while ignoring broken outputs of excluded experiments.
    """
    state = _series(tmp_path)[0]
    image = state.artifact(cst.ARTI_IMG_RAW)
    assert image is not None
    image.write_bytes(b'broken image')
    set_excluded(tmp_path, [state.workdir], True)
    status = inspect_run_compatibility(tmp_path)
    assert not status.outdated
    assert status.states[0].excluded
    report = inspect_run(tmp_path, {'convert': {'enabled': True}})
    assert not report.conflicts and not report.states
    assert not report.needs_decision


def test_membership_changes_flag_masters_without_forcing_rebuild(tmp_path: Path) -> None:
    """
    Rebuild by reaggregation, detect re-inclusion, and remove masters when all series are excluded.
    """
    states: list[ExperimentState] = []
    for index in (1, 2):
        folder = tmp_path / 'acquisition' / f'input_s{index}'
        folder.mkdir(parents=True)
        table = folder / cst.FITS_DISTANCE_PROFILE_NAME
        pd.DataFrame({'distance': [index]}).to_parquet(table, index=False)
        state = ExperimentState.init(folder, folder.parent / 'input.nd2', run_dir=tmp_path)
        states.append(state.with_complete_step(step_name=cst.StepName.DISTANCE_PROFILE,
                                               artifact_kind=cst.ARTI_DIST_PROF, artifact_path=table))
    name = cst.MASTER_DISTANCE_PROFILE_NAME
    master = save_master_analysis_table(states, tmp_path, artifact_kind=cst.ARTI_DIST_PROF, output_name=name)
    assert master is not None
    assert outdated_master_tables(tmp_path, states) == ()
    original = [state.artifact(cst.ARTI_DIST_PROF) for state in states]
    before = [path.read_bytes() for path in original if path is not None]
    changed = [states[0], replace(states[1], excluded=True)]
    assert outdated_master_tables(tmp_path, changed) == (master,)
    from fits.workflows.checks.models import PreflightReport
    report = PreflightReport((), (), (), (), outdated_masters=(master,))
    assert apply_decision({}, report, 'continue') == {}
    assert apply_decision({}, report, 'selected') == {}
    save_master_analysis_table(changed, tmp_path, artifact_kind=cst.ARTI_DIST_PROF, output_name=name)
    assert pd.read_parquet(master)['distance'].tolist() == [1]
    assert outdated_master_tables(tmp_path, changed) == ()
    assert outdated_master_tables(tmp_path, states) == (master,)
    assert before == [path.read_bytes() for path in original if path is not None]
    all_excluded = [replace(state, excluded=True) for state in states]
    assert save_master_analysis_table(all_excluded, tmp_path, artifact_kind=cst.ARTI_DIST_PROF, output_name=name) is None
    assert not master.exists()
    assert outdated_master_tables(tmp_path, states) == (master,)


def test_migrated_checkpoints_require_full_rebuilding_before_selection(tmp_path: Path) -> None:
    """
    Keep metadata-only upgrades active until their processing has been fully rebuilt.
    """
    state = _series(tmp_path)[0]
    save_experiment_state(replace(state, migration_checkpoint='bg_sub'))
    with pytest.raises(ValueError, match='Fully rebuild'):
        set_excluded(tmp_path, [state.workdir], True)
    assert not load_experiment_state(state.workdir).excluded


@pytest.mark.parametrize('method', ['file_action', 'batch', 'conveyor'])
def test_disabled_analysis_is_preserved_until_explicit_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """
    Preserve bypassed combined analysis during normal runs, then rebuild it explicitly.
    """
    from fits.pipeline import start_pipeline
    from fits.tasks.common.table_results import save_parquet
    from fits.workflows.artifacts.provenance import read_metadata
    from fits.workflows.file_management.rebuild import plan_required_rebuild, rebuild_analysis_tables

    def split(source: ScopeIO) -> list[ScopeIO]:
        """
        Provide two series while exercising the real conversion writer.
        """
        return [source, source]

    monkeypatch.setattr(ScopeIO, 'split_series', split)
    states = _series(tmp_path)
    for index, state in enumerate(states):
        raw = state.artifact(cst.ARTI_IMG_RAW)
        assert raw is not None
        metadata = read_metadata(raw)
        payload = metadata.with_artifact(artifact_type=cst.ARTI_DIST_PROF).new_revision([
            {'artifact_path': raw.name, 'created_at': metadata.artifact.created_at}])
        table = save_parquet(pd.DataFrame({'distance': [index]}), state.workdir / cst.FITS_DISTANCE_PROFILE_NAME, payload)
        states[index] = state.with_complete_step(step_name=cst.StepName.DISTANCE_PROFILE,
                                                 artifact_kind=cst.ARTI_DIST_PROF, artifact_path=table)
        save_experiment_state(states[index])
    settings = tmp_path / '.fits/fits_settings.toml'
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(f'run_dir = "{tmp_path}"\nuser_name = "Test"\n[runtime]\nexecution = "{method if method != "file_action" else "batch"}"\n'
                        '[convert]\nenabled = false\n[distance_profile]\nenabled = false\n')
    master = save_master_analysis_table(states, tmp_path, artifact_kind=cst.ARTI_DIST_PROF,
                                       output_name=cst.MASTER_DISTANCE_PROFILE_NAME)
    assert master is not None
    sources = {path: path.read_bytes() for state in states
               if (path := state.artifact(cst.ARTI_DIST_PROF)) is not None}
    set_excluded(tmp_path, [states[0].workdir], True)
    assert not inspect_run_compatibility(tmp_path).outdated
    report = inspect_run(tmp_path, {'convert': {'enabled': False}, 'distance_profile': {'enabled': False}})
    assert report.outdated_masters == (master,)
    assert not report.conflicts
    assert plan_required_rebuild(tmp_path) is None
    if method == 'file_action':
        rebuild_analysis_tables(tmp_path)
    else:
        before = master.read_bytes()
        start_pipeline(settings,
                       artifact_decision=lambda report: pytest.fail('Bypassed tables must not require a decision.'),
                       terminal_progress=False)
        assert master.read_bytes() == before
        assert inspect_run(tmp_path, {}).outdated_masters == (master,)
        rebuild_analysis_tables(tmp_path)
    assert pd.read_parquet(master)['distance'].tolist() == [1]
    assert not inspect_run(tmp_path, {}).needs_decision
    assert sources == {path: path.read_bytes() for path in sources}
    # A newly active experiment's lost result is scheduled before reaggregation.
    set_excluded(tmp_path, [states[0].workdir], False)
    missing = states[0].artifact(cst.ARTI_DIST_PROF)
    assert missing is not None
    missing.unlink()
    plan = plan_required_rebuild(tmp_path)
    assert plan is not None
    assert plan.scope == {states[0].workdir: ('distance_profile',)}
    with pytest.raises(ValueError, match='Rebuild the outdated experiment results'):
        rebuild_analysis_tables(tmp_path)
