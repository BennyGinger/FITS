import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from time import monotonic
import numpy as np
import pytest
import tifffile
from PySide6.QtWidgets import QApplication, QDialog

from fisch.environment.constant import ARTI_IMG, ARTI_TRACK, StepName, WORKFLOW_ORDER
from fisch.workflows.experiments import (
    ExperimentState, load_experiment_state, save_experiment_state)
from fisch.gui.main_window import FischMainWindow
from fisch.gui.settings import SettingsAdapter
from fisch.tasks.reference_mask import ReferenceMaskSession
from scope_io import ScopeIO

_APP = None


@pytest.mark.parametrize("action", ["finalize", "close"])
def test_main_gui_runs_profile_after_drawing_finalization(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch,
                                                        action: str,
                                                        ) -> None:
    """
    Finalizing or closing mask collection lets the main pipeline continue.
    """
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr('fisch.gui.main_window.window.choose_artifacts', lambda report, parent=None, **kwargs: 'continue')
    folder = tmp_path / 'experiment'
    folder.mkdir()
    (tmp_path / "original.nd2").touch()
    source = folder / 'proc_array_raw.tif'
    tifffile.imwrite(source, np.arange(64, dtype=np.uint16).reshape(8, 8), imagej=True, metadata={'axes': 'YX'})
    reader = ScopeIO.from_path(source)
    reader.save_array(reader.get_array().array, output_path=source,
                       custom_metadata={'pipeline_meta': {'version': '5.0.0'}})
    save_experiment_state(
        ExperimentState.init(folder, tmp_path / "original.nd2").with_complete_step(
            step_name=StepName.CONVERT,
            artifact_kind="image_raw",
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
    window = FischMainWindow(adapter)
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
                assert not (folder / 'proc_distance_profile.parquet').exists()
                saw_window = True
                monkeypatch.setattr(collection, '_confirm', lambda *args: True)
                if action == "finalize":
                    collection._finish_experiment()
                else:
                    collection.close()
        assert window._thread is None, 'Pipeline did not finish'
        assert not errors, errors
        assert saw_window, window.console.toPlainText()
        assert (folder / 'proc_distance_profile.parquet').is_file()
        assert 'cancelled' not in window.console.toPlainText().lower()
        assert window._mask_collection is None
    finally:
        if window._worker is not None:
            window._worker.interaction.cancel()
            deadline = monotonic() + 5
            while window._thread is not None and monotonic() < deadline:
                _APP.processEvents()
        window.close()


def test_main_gui_opens_manual_tracking_editor_without_running_pipeline(tmp_path: Path) -> None:
    """
    Open existing tracking separately and leave its data intact when the editor closes.
    """
    from scope_io import ScopeIO
    from fisch.gui.viewer.tracking import TrackingViewerWindow

    global _APP
    _APP = QApplication.instance() or QApplication([])
    raw = tmp_path / 'input.tif'
    tifffile.imwrite(raw, np.arange(64, dtype=np.uint16).reshape(8, 8),
                     imagej=True, metadata={'axes': 'YX'})
    folder = tmp_path / 'experiment'
    folder.mkdir()
    reader = ScopeIO.from_path(raw)
    image = reader.save_array(reader.get_array().array, output_path=folder / 'proc_array_raw.tif',
                               custom_metadata={'pipeline_meta': {'version': '5.0.0'}})
    reader = ScopeIO.from_path(image)
    tracking = reader.save_array(np.ones((8, 8), dtype=np.uint16), artifact_kind=ARTI_TRACK,
                                  output_path=folder / 'proc_masks_track.tif')
    current = ExperimentState.init(folder, raw, run_dir=tmp_path)
    current = current.with_complete_step(step_name=StepName.CONVERT, artifact_kind='image_raw', artifact_path=image)
    current = current.with_complete_step(step_name=StepName.TRACK, artifact_kind=ARTI_TRACK, artifact_path=tracking)
    save_experiment_state(current)
    before = tracking.read_bytes()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'test'
    adapter.save_to_run_dir()
    window = FischMainWindow(adapter)
    try:
        assert StepName.EDIT_TRACK not in window._editors
        assert window.tracking_edit_button.isEnabled()
        window.tracking_edit_button.click()
        editor = window._manual_tracking_editor
        assert isinstance(editor, TrackingViewerWindow)
        assert editor._tracking_session is not None
        assert not editor._tracking_session.read_only
        assert window._thread is None
        editor.close()
        assert tracking.read_bytes() == before
        final = load_experiment_state(folder)
        assert final.artifact(ARTI_TRACK) == tracking
        assert StepName.EDIT_TRACK not in final.completed_steps
    finally:
        window.close()
