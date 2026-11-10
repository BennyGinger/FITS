"""Processing settings conflicts use recorded parameters and propagate downstream."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import tifffile
from scope_io import ScopeIO
from scope_io.metadata.models import ImageMetadata

from fisch.environment import constant as cst
from fisch.gui.settings import SettingsAdapter
from fisch.settings.loader import resolve_step_params
from fisch.workflows.artifacts.provenance import revision_payload
from fisch.workflows.checks.artifacts import inspect_run
from fisch.workflows.checks.models import ArtifactRecord
from fisch.workflows.checks.settings import settings_problem
from fisch.workflows.checks.decisions import apply_decision
from fisch.workflows.definitions.inputs import configured_profile
from fisch.workflows.definitions.registry import REGISTRY
from fisch.workflows.experiments import ExperimentState, save_experiment_state


def test_segmentation_settings_conflict_propagates_and_can_be_reverted(tmp_path: Path) -> None:
    """
    Changing a channel diameter affects masks and tracking but not source images.
    """
    source = tmp_path / "input.tif"
    pixels = np.zeros((8, 8), dtype=np.uint16)
    tifffile.imwrite(source, pixels, metadata={"axes": "YX"})
    state = ExperimentState.init(tmp_path, source)
    adapter = SettingsAdapter()
    adapter.set_field_value(cst.StepName.CONVERT, "channel_labels", ["Green"])
    adapter.set_segment_channels([{"channel": "Green", "user_settings": {"diameter": 20}}])
    adapter.set_field_value(cst.StepName.TRACK, "channel_to_track", ["Green"])
    for step in (cst.StepName.SEGMENT, cst.StepName.TRACK):
        adapter.set_step_enabled(step, True)
    reader = ScopeIO.from_path(source)
    for step in (cst.StepName.CONVERT, cst.StepName.SEGMENT, cst.StepName.TRACK):
        spec = REGISTRY[step]
        model = spec.model_validate(resolve_step_params(step, adapter.as_mapping()[step]))
        if step == cst.StepName.SEGMENT:
            params = adapter.segmentation_settings().channels[0].to_payload_dict()
        elif step == cst.StepName.TRACK:
            params = {"channel_to_track": ["Green"], "backend": "trackastra",
                      "postprocess": model.postprocess.model_dump(), **model.trackastra}
        else:
            params = model.model_dump()
        state = state.with_metadata(step_name=step, created_by=spec.profile.distribution,
                                    exported_channel="all" if step == cst.StepName.CONVERT else [0],
                                    channels_params=params,
                                    )
        profile = configured_profile(spec.profile, adapter.as_mapping())
        payload = revision_payload(reader, state, profile, export_channels="all")
        output = tmp_path / spec.profile.output_name
        reader.save_array(pixels, channel_labels=["Green"], metadata=payload, output_path=output)
        state = state.with_complete_step(step_name=step, artifact_kind=spec.profile.output_artifact, artifact_path=output)
        reader = ScopeIO.from_path(output)
    save_experiment_state(state)
    assert not inspect_run(tmp_path, adapter.as_mapping(), for_execution=False).conflicts
    adapter.set_field_value(cst.StepName.SEGMENT, "workers", 5)
    adapter.set_field_value(cst.StepName.SEGMENT, "execution", "serial")
    assert not inspect_run(tmp_path, adapter.as_mapping(), for_execution=False).conflicts
    adapter.set_segment_channels([{"channel": "Green", "user_settings": {"diameter": 25}}])
    report = inspect_run(tmp_path, adapter.as_mapping(), for_execution=False)
    assert {record.step for record in report.conflicts} == {cst.StepName.SEGMENT, cst.StepName.TRACK}
    assert "Processing settings differ" in next(record.problem for record in report.conflicts if record.step == cst.StepName.SEGMENT)
    continued = apply_decision(adapter.as_mapping(), report, "continue")
    assert not continued[cst.StepName.SEGMENT]["params"]["overwrite"]
    rebuilt = apply_decision(adapter.as_mapping(), report, "rebuild")
    assert rebuilt[cst.StepName.SEGMENT]["params"]["overwrite"]
    assert rebuilt[cst.StepName.TRACK]["params"]["overwrite"]
    adapter.set_segment_channels([{"channel": "Green", "user_settings": {"diameter": 20}}])
    assert not inspect_run(tmp_path, adapter.as_mapping(), for_execution=False).conflicts


@pytest.mark.parametrize('step,context,algorithm', [
    (cst.StepName.REGISTER_CHANNEL, 'channel_shift', 'cv2'),
    (cst.StepName.REGISTER_TIME, 'linear_drift', 'pystackreg'),
])
@pytest.mark.parametrize('alias_only', [False, True])
def test_registration_backend_alias_does_not_mark_rebuilt_results_outdated(step: cst.StepName,
                                                                          context: str,
                                                                          algorithm: str,
                                                                          alias_only: bool,
                                                                          ) -> None:
    """
    Accept equivalent recorded registration names while detecting real processing changes.
    """
    config: dict[str, Any] = {step: {'enabled': True, 'params': {'context': context}}}
    settings = REGISTRY[step].model_validate(resolve_step_params(step, config[step]))
    params = {**settings.to_payload_dict(), 'algorithm': algorithm, 'backend': algorithm, 'method': 'translation'}
    if alias_only:
        params.pop('algorithm')
    metadata = ImageMetadata(custom_metadata={'steps': {step: {'params': params}}})
    record = ArtifactRecord(Path('registration.tif'), step, metadata)
    assert not settings_problem(record, config)
    config[step]['params']['method'] = 'affine'
    assert 'Processing settings differ' in settings_problem(record, config)
    config[step]['params']['method'] = 'translation'
    config[step]['params']['algorithm'] = 'scikit'
    assert 'Processing settings differ' in settings_problem(record, config)


def test_conflicting_registration_aliases_remain_a_warning() -> None:
    """
    Preserve a warning when saved backend and algorithm fields disagree.
    """
    step = cst.StepName.REGISTER_CHANNEL
    config: dict[str, Any] = {step: {'enabled': True, 'params': {'context': 'channel_shift'}}}
    settings = REGISTRY[step].model_validate(resolve_step_params(step, config[step]))
    metadata = ImageMetadata(custom_metadata={'steps': {step: {'params': {
        **settings.to_payload_dict(), 'algorithm': 'cv2', 'backend': 'scikit', 'method': 'translation'}}}})
    assert 'Processing settings differ' in settings_problem(ArtifactRecord(Path('registration.tif'), step, metadata), config)
