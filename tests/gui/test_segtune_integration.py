import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fits.environment.constant import StepName
from fits.gui.settings_adapter import SettingsAdapter
from fits.gui.viewer.segmentation_window import SegmentationTunerWindow
from fits.gui.viewer.mask_window import MaskDrawingWindow
from fits.gui.window import FitsMainWindow
from fits.settings.models import SegmentSettings

_APP = None


def application():
    global _APP
    _APP = QApplication.instance() or QApplication([])


def test_tuner_round_trip_and_close(monkeypatch, tmp_path):
    application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_field_value(StepName.SEGMENT, "workers", 3)
    adapter.set_field_value(StepName.SEGMENT, "user_settings.diameter", 19)
    window = FitsMainWindow(adapter)
    window.user_name_edit.setText("Unsaved user")
    window._open_segmentation_tuner()
    tuner = window._segmentation_tuner
    assert tuner._provided_settings.user_settings["diameter"] == 19
    assert tuner.directory_browser.root_path == tmp_path
    assert tuner.windowModality() == Qt.WindowModality.WindowModal
    assert tuner.settings_panel.apply_button.text() == "Apply and close"
    chosen = SegmentSettings(channel_to_segment=["GFP"], nuclear_channel=None,
                             do_denoise=False, user_settings={"diameter": 31})
    monkeypatch.setattr(tuner, "current_settings", lambda: chosen)
    tuner._apply_settings()
    assert not tuner.isVisible()
    assert adapter.field_value(StepName.SEGMENT, "channel_to_segment") == ["GFP"]
    assert adapter.field_value(StepName.SEGMENT, "nuclear_channel") == "None"
    assert adapter.field_value(StepName.SEGMENT, "workers") == 3
    assert adapter.user_name == "Unsaved user"
    assert window._editors[StepName.SEGMENT].widgets["user_settings.diameter"].value() == 31
    adapter.save_to_run_dir()
    reloaded = SettingsAdapter()
    reloaded.load(tmp_path / "fits_settings.toml")
    settings = SegmentSettings.model_validate(reloaded.as_mapping()["segment"]["params"])
    assert settings.user_settings["diameter"] == 31
    assert settings.nuclear_channel is None
    window.close()


def test_close_without_apply_leaves_settings_unchanged(tmp_path):
    application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    before = adapter.as_mapping()
    window._open_segmentation_tuner()
    window._segmentation_tuner.settings_panel.denoise.setChecked(False)
    window._segmentation_tuner.close()
    assert adapter.as_mapping() == before
    window.close()


def test_drawmask_exposes_both_mask_types():
    application()
    viewer = MaskDrawingWindow()
    assert [viewer.tool_tabs.tabText(i) for i in range(2)] == ["Reference", "ROI"]
    assert viewer.directory_browser.model.nameFilters() == [
        "fits_array.tif", "fits_ref_*.tif", "fits_roi_*.tif"]
    viewer.close()


def test_invalid_apply_keeps_tuner_open():
    application()
    viewer = SegmentationTunerWindow(close_on_apply=True)
    applied = []
    viewer.settings_applied.connect(applied.append)
    viewer.show()
    viewer._apply_settings()
    assert viewer.isVisible()
    assert applied == []
    viewer.close()
