from importlib import import_module
from pathlib import Path

import numpy as np
import pytest
from scope_io import ScopeIO
import tifffile

from fits.environment import constant as cst
from fits.gui.settings import SettingsAdapter
from fits.pipeline import start_pipeline
from fits.workflows.experiments import discover_saved_states, save_experiment_state


class IdentityRegistration:
    def __init__(self, **kwargs):
        pass
    def fit_time(self, **kwargs):
        pass
    def fit_channel(self, **kwargs):
        pass
    def apply(self, *, array, axes):
        return np.asarray(array) + 1


def test_intermediates_preserve_inputs_and_bypass_disabled_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Rerun the last image stage without reviewing nonexistent downstream results.
    """
    for module in ("register_channel", "register_time"):
        monkeypatch.setattr(import_module("fits.tasks.registration." + module), "RegisterModel", IdentityRegistration)
    monkeypatch.setattr(import_module("fits.tasks.bg_sub"), "bg_sub", lambda array, **kw: array.astype(np.float32) + 0.5)
    pixels = np.arange(3 * 2 * 8 * 8, dtype=np.uint16).reshape(3, 2, 8, 8)
    tifffile.imwrite(tmp_path / "source.tif", pixels, photometric="minisblack", metadata={"axes": "TCYX"})
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "Test"
    adapter.set_runtime_value("execution", "batch")
    enabled = {cst.StepName.CONVERT, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME, cst.StepName.BG_SUB}
    for step in cst.WORKFLOW_ORDER:
        adapter.set_step_enabled(step, step in enabled)
        adapter.set_field_value(step, "execution", "serial")
    adapter.set_field_value(cst.StepName.CONVERT, "channel_labels", ["Red", "Green"])
    adapter.set_field_value(cst.StepName.REGISTER_CHANNEL, "reference_channel", "Red")
    settings = adapter.save_to_run_dir()
    start_pipeline(settings, terminal_progress=False, artifact_decision=lambda report: pytest.fail("Unexpected conflict review"))
    state = discover_saved_states(tmp_path)[0]
    raw = state.artifact(cst.ARTI_IMG_RAW)
    channel = state.artifact(cst.ARTI_IMG_CHANNEL)
    time = state.artifact(cst.ARTI_IMG_TIME)
    bg = state.artifact(cst.ARTI_IMG_BGSUB)
    assert [p.name for p in (raw, channel, time, bg)] == list(cst.IMAGE_STAGE_NAMES)
    np.testing.assert_array_equal(ScopeIO.from_path(raw).get_array().array, pixels)
    np.testing.assert_array_equal(ScopeIO.from_path(bg).get_array().array, pixels + 2.5)
    metadata = ScopeIO.from_path(bg).reader.metadata
    assert metadata.artifact.derived_from[0]["created_at"] == ScopeIO.from_path(time).reader.metadata.artifact.created_at

    # A bypassed downstream result is retained and does not require a decision.
    reader = ScopeIO.from_path(bg)
    segmentation = state.workdir / cst.FITS_MASK_SEG
    payload = reader.build_payload(export_channels="all", artifact_type=cst.ARTI_SEG,
                                   custom_metadata={"pipeline_meta": {"version": "4.0.0"}}).new_revision(
                                       [{"artifact_path": bg.name, "created_at": metadata.artifact.created_at}])
    reader.save_array(pixels, metadata=payload, output_path=segmentation)
    state = state.with_complete_step(step_name=cst.StepName.SEGMENT,
                                    artifact_kind=cst.ARTI_SEG, artifact_path=segmentation)
    save_experiment_state(state)
    preserved = segmentation.read_bytes()

    adapter.set_step_enabled(cst.StepName.REGISTER_TIME, False)
    adapter.set_field_value(cst.StepName.BG_SUB, "overwrite", True)
    adapter.save_to_run_dir()
    start_pipeline(settings, terminal_progress=False, artifact_decision=lambda report: pytest.fail("Unexpected terminal-overwrite review"))
    np.testing.assert_array_equal(ScopeIO.from_path(bg).get_array().array, pixels + 1.5)
    assert ScopeIO.from_path(bg).reader.metadata.artifact.derived_from[0]["created_at"] == (
        ScopeIO.from_path(channel).reader.metadata.artifact.created_at)
    assert segmentation.read_bytes() == preserved
    from fits.workflows.checks.artifacts import inspect_run
    report = inspect_run(tmp_path, adapter.as_mapping())
    assert not report.needs_decision
    assert any("Bypassed step 'segment'" in warning for warning in report.warnings)
    adapter.set_step_enabled(cst.StepName.SEGMENT, True)
    assert inspect_run(tmp_path, adapter.as_mapping()).needs_decision


def test_real_artifacts_segmentation_tracking_and_analysis_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Preserve lineage and rerun terminal Quantification without reviewing the overwrite.
    """
    from types import SimpleNamespace
    from fits.workflows.artifacts.provenance import read_metadata
    from fits.workflows.file_management.compaction import compact_run
    from fits.workflows.checks.artifacts import inspect_run
    class Segmenter:
        output_axis_order = 'TYX'
        def setup(self): pass
        def run(self, array, axes):
            result = np.zeros((3, 8, 8), dtype=np.uint16)
            result[:, 2:5, 2:5] = 1
            return result
    monkeypatch.setattr(import_module('fits.tasks.segmentation.channels').CellposeWrapper,
                        'from_dict', lambda settings: Segmenter())
    monkeypatch.setattr(import_module('fits.tasks.tracking.track'), 'create_tracker',
                        lambda settings: SimpleNamespace(track=lambda image, masks: masks))
    tifffile.imwrite(tmp_path / 'source.tif', np.ones((3, 8, 8), dtype=np.uint16),
                     photometric='minisblack', metadata={'axes': 'TYX'})
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_runtime_value('execution', 'batch')
    for step in cst.WORKFLOW_ORDER:
        adapter.set_step_enabled(step, step in (cst.StepName.CONVERT, cst.StepName.SEGMENT, cst.StepName.TRACK, cst.StepName.EXTRACT))
        adapter.set_field_value(step, 'execution', 'serial')
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', ['Red'])
    adapter.set_segment_channels([{'channel': 'Red'}])
    adapter.set_field_value(cst.StepName.TRACK, 'channel_to_track', ['Red'])
    settings = adapter.save_to_run_dir()
    start_pipeline(settings, terminal_progress=False)
    state = discover_saved_states(tmp_path)[0]
    track = read_metadata(state.artifact(cst.ARTI_TRACK))
    assert {ref['artifact_path'] for ref in track.artifact.derived_from} == {cst.FITS_MASK_SEG, cst.FITS_ARRAY_RAW}
    table = read_metadata(state.artifact(cst.ARTI_QUANTI))
    assert state.artifact(cst.ARTI_QUANTI).name == cst.FITS_QUANTI_NAME
    assert {ref['artifact_path'] for ref in table.artifact.derived_from} == {cst.FITS_MASK_TRACK, cst.FITS_ARRAY_RAW}
    assert not inspect_run(tmp_path, adapter.as_mapping()).conflicts
    adapter.set_field_value(cst.StepName.EXTRACT, 'overwrite', True)
    adapter.set_field_value(cst.StepName.EXTRACT, 'membrane_thickness', 2.0)
    adapter.save_to_run_dir()
    assert not inspect_run(tmp_path, adapter.as_mapping()).needs_decision
    start_pipeline(settings, terminal_progress=False,
                   artifact_decision=lambda report: pytest.fail("Unexpected quantification-overwrite review"))
    assert read_metadata(state.artifact(cst.ARTI_QUANTI)).artifact.created_at != table.artifact.created_at
    assert read_metadata(state.artifact(cst.ARTI_TRACK)).artifact.created_at == track.artifact.created_at
    adapter.set_field_value(cst.StepName.EXTRACT, 'overwrite', False)
    # Bypass stale tracking and quantify segmentation, preserving the tracked pixels.
    tracking_path = state.artifact(cst.ARTI_TRACK)
    tracking_reader = ScopeIO.from_path(tracking_path)
    stale = tracking_reader.reader.metadata.new_revision(
        [{"artifact_path": cst.FITS_MASK_SEG, "created_at": "superseded revision"},
         *[ref for ref in track.artifact.derived_from if ref['artifact_path'] != cst.FITS_MASK_SEG]])
    tracking_reader.save_array(tracking_reader.get_array().array, metadata=stale, output_path=tracking_path)
    track = read_metadata(tracking_path)
    preserved_tracking = tracking_path.read_bytes()
    adapter.set_step_enabled(cst.StepName.TRACK, False)
    adapter.set_field_value(cst.StepName.EXTRACT, 'overwrite', True)
    adapter.save_to_run_dir()
    report = inspect_run(tmp_path, adapter.as_mapping())
    assert not report.needs_decision
    assert any("Bypassed step 'track'" in warning for warning in report.warnings)
    start_pipeline(settings, terminal_progress=False,
                   artifact_decision=lambda report: pytest.fail("Bypassed tracking must not require a decision"))
    assert tracking_path.read_bytes() == preserved_tracking
    assert {ref['artifact_path'] for ref in read_metadata(state.artifact(cst.ARTI_QUANTI)).artifact.derived_from} == {
        cst.FITS_MASK_SEG, cst.FITS_ARRAY_RAW}
    adapter.set_step_enabled(cst.StepName.TRACK, True)
    adapter.set_field_value(cst.StepName.EXTRACT, 'overwrite', False)
    assert inspect_run(tmp_path, adapter.as_mapping()).needs_decision
    segmentation = state.artifact(cst.ARTI_SEG)
    reader = ScopeIO.from_path(segmentation)
    changed = reader.reader.metadata.new_revision(reader.reader.metadata.artifact.derived_from)
    reader.save_array(reader.get_array().array, metadata=changed, output_path=segmentation)
    assert any(row.step == cst.StepName.TRACK for row in inspect_run(tmp_path, adapter.as_mapping()).conflicts)
    compact_run(tmp_path, choose=lambda report: 'continue', confirm=lambda plan: True)
    state = discover_saved_states(tmp_path)[0]
    assert state.artifact(cst.ARTI_TRACK).name == cst.FITS_MASKS_COMPACTED
    assert state.compaction_conflicts_accepted
    assert read_metadata(state.artifact(cst.ARTI_TRACK)).artifact.created_at == track.artifact.created_at
