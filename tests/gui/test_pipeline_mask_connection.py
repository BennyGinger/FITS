import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from time import monotonic
import numpy as np
import pytest
import tifffile
from PySide6.QtWidgets import QApplication, QDialog

from fits.environment.constant import ARTI_IMG, ARTI_TRACK, StepName, WORKFLOW_ORDER
from fits.workflows.experiments import (
    ExperimentState, load_experiment_state, save_experiment_state)
from fits.gui.main_window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.tasks.reference_mask import ReferenceMaskSession

_APP = None


@pytest.mark.parametrize("action", ["finalize", "cancel"])
def test_main_gui_runs_profile_after_drawing_finalization(tmp_path, monkeypatch, action):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    folder = tmp_path / 'experiment'
    folder.mkdir()
    source = folder / 'fits_array.tif'
    tifffile.imwrite(source, np.arange(64, dtype=np.uint16).reshape(8, 8), imagej=True, metadata={'axes': 'YX'})
    save_experiment_state(
        ExperimentState.init(folder, folder / "original.nd2").with_complete_step(
            step_name=StepName.CONVERT,
            artifact_kind=ARTI_IMG,
            artifact_path=source,
        )
    )
    session = ReferenceMaskSession(source)
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[0, 0] = 1
    session.set_mask_plane(mask)
    session.save('edge')
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'test'
    for step in WORKFLOW_ORDER:
        adapter.set_step_enabled(step, step == StepName.DISTANCE_PROFILE)
    adapter.set_field_value(StepName.DISTANCE_PROFILE, 'frame_workers', 1)
    window = FitsMainWindow(adapter)
    errors = []
    monkeypatch.setattr(window, '_pipeline_failed', lambda message, details: errors.append(details))
    window._run_pipeline()
    saw_window = False
    deadline = monotonic() + 15
    try:
        while window._thread is not None and monotonic() < deadline:
            _APP.processEvents()
            collection = window._mask_collection
            if collection is not None and collection._active is not None:
                assert collection.load_button.isHidden()
                assert not (folder / 'fits_distance_profile.parquet').exists()
                saw_window = True
                monkeypatch.setattr(collection, '_confirm', lambda *args: True)
                if action == "finalize":
                    collection._finish_experiment()
                else:
                    collection.close()
        assert window._thread is None, 'Pipeline did not finish'
        assert not errors, errors
        assert saw_window
        assert (folder / 'fits_distance_profile.parquet').is_file() == (action == 'finalize')
        if action == 'cancel':
            assert 'cancelled' in window.console.toPlainText().lower()
        assert window._mask_collection is None
    finally:
        if window._worker is not None:
            window._worker.interaction.cancel()
            deadline = monotonic() + 5
            while window._thread is not None and monotonic() < deadline:
                _APP.processEvents()
        window.close()


def test_main_gui_opens_tracking_editor_and_can_keep_original(tmp_path, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    folder = tmp_path / 'experiment'
    folder.mkdir()
    image = folder / 'fits_array.tif'
    tracking = folder / 'fits_track.tif'
    tifffile.imwrite(image, np.arange(64, dtype=np.uint16).reshape(8, 8),
                     imagej=True, metadata={'axes': 'YX'})
    tifffile.imwrite(tracking, np.ones((8, 8), dtype=np.uint16),
                     imagej=True, metadata={'axes': 'YX'})
    current = ExperimentState.init(folder, folder / 'original.nd2')
    current = current.with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind=ARTI_IMG,
        artifact_path=image)
    current = current.with_complete_step(
        step_name=StepName.TRACK,
        artifact_kind=ARTI_TRACK,
        artifact_path=tracking)
    save_experiment_state(current)

    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'test'
    for step_name in WORKFLOW_ORDER:
        adapter.set_step_enabled(step_name, step_name == StepName.EDIT_TRACK)
    window = FitsMainWindow(adapter)
    errors = []
    monkeypatch.setattr(
        window, '_pipeline_failed',
        lambda message, details: errors.append(details))
    window._run_pipeline()
    saw_editor = False
    deadline = monotonic() + 15
    try:
        while window._thread is not None and monotonic() < deadline:
            _APP.processEvents()
            editor = window._tracking_editor
            if editor is not None:
                saw_editor = True
                editor.use_original_button.click()
        assert window._thread is None, 'Pipeline did not finish'
        assert not errors, errors
        assert saw_editor
        final = load_experiment_state(folder)
        assert final.artifact(ARTI_TRACK) == tracking
        assert StepName.EDIT_TRACK in final.completed_steps
        assert window._tracking_editor is None
    finally:
        if window._worker is not None:
            window._worker.interaction.cancel()
            deadline = monotonic() + 5
            while window._thread is not None and monotonic() < deadline:
                _APP.processEvents()
        window.close()
