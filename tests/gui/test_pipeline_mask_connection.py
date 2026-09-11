import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from time import monotonic
import numpy as np
import pytest
import tifffile
from PySide6.QtWidgets import QApplication, QDialog

from fits.environment.constant import ARTI_IMG, StepName, WORKFLOW_ORDER
from fits.environment.state import ExperimentState
from fits.gui.settings_adapter import SettingsAdapter
from fits.gui.window import FitsMainWindow
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
    ExperimentState.init(folder, folder / "original.nd2").with_complete_step(
        step_name=StepName.CONVERT, artifact_kind=ARTI_IMG, artifact_path=source).save_state()
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
