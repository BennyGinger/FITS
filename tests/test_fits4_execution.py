from importlib import import_module

import numpy as np
from fits_io import FitsIO
import tifffile

from fits.environment import constant as cst
from fits.gui.settings import SettingsAdapter
from fits.pipeline import start_pipeline
from fits.workflows.experiments import discover_saved_states


class IdentityRegistration:
    def __init__(self, **kwargs):
        pass
    def fit_time(self, **kwargs):
        pass
    def fit_channel(self, **kwargs):
        pass
    def apply(self, *, array, axes):
        return np.asarray(array) + 1


def test_intermediates_preserve_inputs_and_bypass_disabled_stage(tmp_path, monkeypatch):
    for module in ("register_channel", "register_time"):
        monkeypatch.setattr(import_module("fits.tasks.registration." + module), "RegisterModel", IdentityRegistration)
    monkeypatch.setattr(import_module("fits.tasks.bg_sub"), "bg_sub", lambda array, **kw: array.astype(np.float32) + 0.5)
    pixels = np.arange(3 * 8 * 8, dtype=np.uint16).reshape(3, 8, 8)
    tifffile.imwrite(tmp_path / "source.tif", pixels, photometric="minisblack", metadata={"axes": "TYX"})
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "Test"
    adapter.set_runtime_value("execution", "batch")
    enabled = {cst.StepName.CONVERT, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME, cst.StepName.BG_SUB}
    for step in cst.WORKFLOW_ORDER:
        adapter.set_step_enabled(step, step in enabled)
        adapter.set_field_value(step, "execution", "serial")
    adapter.set_field_value(cst.StepName.CONVERT, "channel_labels", ["Red"])
    adapter.set_field_value(cst.StepName.REGISTER_CHANNEL, "reference_channel", "Red")
    settings = adapter.save_to_run_dir()
    start_pipeline(settings, terminal_progress=False, artifact_decision=lambda report: "rebuild")
    state = discover_saved_states(tmp_path)[0]
    raw = state.artifact(cst.ARTI_IMG_RAW)
    channel = state.artifact(cst.ARTI_IMG_CHANNEL)
    time = state.artifact(cst.ARTI_IMG_TIME)
    bg = state.artifact(cst.ARTI_IMG_BGSUB)
    assert [p.name for p in (raw, channel, time, bg)] == list(cst.IMAGE_STAGE_NAMES)
    np.testing.assert_array_equal(FitsIO.from_path(raw).get_array().array, pixels)
    np.testing.assert_array_equal(FitsIO.from_path(bg).get_array().array, pixels + 2.5)
    metadata = FitsIO.from_path(bg).reader.metadata
    assert metadata.fits_io.derived_from[0]["created_at"] == FitsIO.from_path(time).reader.metadata.fits_io.created_at

    adapter.set_step_enabled(cst.StepName.REGISTER_TIME, False)
    adapter.set_field_value(cst.StepName.BG_SUB, "overwrite", True)
    adapter.save_to_run_dir()
    start_pipeline(settings, terminal_progress=False, artifact_decision=lambda report: "rebuild")
    np.testing.assert_array_equal(FitsIO.from_path(bg).get_array().array, pixels + 1.5)
    assert FitsIO.from_path(bg).reader.metadata.fits_io.derived_from[0]["created_at"] == (
        FitsIO.from_path(channel).reader.metadata.fits_io.created_at)


def test_real_artifacts_segmentation_tracking_and_analysis_provenance(tmp_path, monkeypatch):
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
    assert {ref['artifact_path'] for ref in track.fits_io.derived_from} == {cst.FITS_MASK_SEG, cst.FITS_ARRAY_RAW}
    table = read_metadata(state.artifact(cst.ARTI_QUANTI))
    assert {ref['artifact_path'] for ref in table.fits_io.derived_from} == {cst.FITS_MASK_TRACK, cst.FITS_ARRAY_RAW}
    assert not inspect_run(tmp_path, adapter.as_mapping()).conflicts
    segmentation = state.artifact(cst.ARTI_SEG)
    reader = FitsIO.from_path(segmentation)
    changed = reader.reader.metadata.new_revision(reader.reader.metadata.fits_io.derived_from)
    reader.save_array(reader.get_array().array, metadata=changed, output_path=segmentation)
    assert any(row.step == cst.StepName.TRACK for row in inspect_run(tmp_path, adapter.as_mapping()).conflicts)
    compact_run(tmp_path, choose=lambda report: 'continue', confirm=lambda plan: True)
    state = discover_saved_states(tmp_path)[0]
    assert state.artifact(cst.ARTI_TRACK).name == cst.FITS_MASKS_COMPACTED
    assert state.compaction_conflicts_accepted
    assert read_metadata(state.artifact(cst.ARTI_TRACK)).fits_io.created_at == track.fits_io.created_at
