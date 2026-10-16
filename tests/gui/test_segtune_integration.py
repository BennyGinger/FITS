import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fits.environment.constant import StepName
from fits.gui.main_window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.gui.viewer.masks import MaskDrawingWindow
from fits.gui.viewer.segmentation import SegmentationTunerWindow
from fits.settings.models import SegmentSettings

_APP = None


@pytest.fixture(autouse=True)
def _skip_background_model_initialization(monkeypatch):
    monkeypatch.setattr(
        SegmentationTunerWindow,
        "_initialize_selected_model",
        lambda self: None,
    )


def application():
    global _APP
    _APP = QApplication.instance() or QApplication([])


def test_tuner_round_trip_and_close(monkeypatch, tmp_path):
    application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_field_value(StepName.SEGMENT, "workers", 3)
    adapter.set_segment_channels([{"channel": "GFP", "user_settings": {"diameter": 19}}])
    window = FitsMainWindow(adapter)
    window.user_name_edit.setText("Unsaved user")
    window._open_segmentation_tuner()
    tuner = window._segmentation_tuner
    assert tuner._provided_settings.channels[0].user_settings["diameter"] == 19
    assert tuner.directory_browser.root_path == tmp_path
    assert tuner.windowModality() == Qt.WindowModality.WindowModal
    assert tuner.settings_panel.apply_button.text() == "Apply and close"
    chosen = SegmentSettings(channels=[{"channel": "GFP", "nuclear_channel": None,
                                         "do_denoise": False, "user_settings": {"diameter": 31}}])
    monkeypatch.setattr(tuner, "current_settings", lambda: chosen)
    tuner._apply_settings()
    assert not tuner.isVisible()
    assert adapter.segment_channels()[0]["channel"] == "GFP"
    assert adapter.segment_channels()[0]["nuclear_channel"] == "None"
    assert adapter.field_value(StepName.SEGMENT, "workers") == 3
    assert adapter.user_name == "Unsaved user"
    assert window._editors[StepName.SEGMENT].channel_widgets[0]["user_settings.diameter"].value() == 31
    adapter.save_to_run_dir()
    reloaded = SettingsAdapter()
    reloaded.load(tmp_path / ".fits" / "fits_settings.toml")
    settings = reloaded.segmentation_settings().channels[0]
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


def test_tuner_styles_actions_and_preview_restores_overlay():
    application()
    viewer = SegmentationTunerWindow()

    assert viewer.width() >= 1500
    assert viewer.height() >= 950
    panel_layout = viewer.settings_panel.layout()
    channel_list_index = panel_layout.indexOf(viewer.channel_settings_list)
    assert channel_list_index == panel_layout.count() - 1
    assert viewer.channel_settings_list.maximumHeight() == 300
    actions_layout = viewer.preview_actions.layout()
    assert [actions_layout.itemAt(i).widget() for i in range(3)] == [
        viewer.settings_panel.run_button,
        viewer.add_channel_button,
        viewer.settings_panel.apply_button,
    ]
    viewer.show()
    QApplication.processEvents()
    assert viewer.preview_actions.mapToGlobal(
        viewer.preview_actions.rect().topLeft()).x() > viewer.lut_controls.mapToGlobal(
            viewer.lut_controls.rect().topRight()).x()
    assert viewer.settings_panel.run_button.width() == viewer.add_channel_button.width()
    assert viewer.settings_panel.run_button.width() == viewer.settings_panel.apply_button.width()
    assert "#d97706" in viewer.settings_panel.run_button.styleSheet()
    assert "#4f8f5b" in viewer.add_channel_button.styleSheet()
    assert "#16803b" in viewer.settings_panel.apply_button.styleSheet()
    viewer.show_mask.setChecked(False)
    viewer._run_preview()

    assert viewer.show_mask.isChecked()
    viewer.close()
