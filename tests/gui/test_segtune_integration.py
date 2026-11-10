import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import numpy as np
import tifffile
from scope_io import ScopeIO
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout

from fisch.environment.constant import StepName
from fisch.gui.main_window import FischMainWindow
from fisch.gui.settings import SettingsAdapter
from fisch.gui.viewer.masks import MaskDrawingWindow
from fisch.gui.viewer.segmentation import SegmentationTunerWindow
from fisch.settings.models import SegmentSettings
from fisch.workflows.experiments import ExperimentState, save_experiment_state

_APP = None


@pytest.fixture(autouse=True)
def _skip_background_model_initialization(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep settings tests free of model loading and unrelated discard dialogs.
    """
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(
        SegmentationTunerWindow,
        "_initialize_selected_model",
        lambda self: None,
    )


def application() -> None:
    """
    Finish model-choice discovery before testing synchronous tuner interactions.
    """
    global _APP
    _APP = QApplication.instance() or QApplication([])
    from fisch.gui.segmentation_models.loader import model_options_loader
    loader = model_options_loader()
    loader.start()
    loader.wait()
    _APP.processEvents()


def _write_current_run(root: Path) -> None:
    """
    Give settings-save tests a valid current portable image rather than an empty TIFF.
    """
    raw = root / 'input.tif'
    pixels = np.zeros((8, 8), dtype=np.uint16)
    tifffile.imwrite(raw, pixels, imagej=True, metadata={'axes': 'YX'})
    directory = root / 'series'
    directory.mkdir()
    image = ScopeIO.from_path(raw).save_array(pixels, output_path=directory / 'proc_array_raw.tif',
                                             channel_labels=['GFP'],
                                             custom_metadata={'pipeline_meta': {'version': '5.0.0'}})
    state = ExperimentState.init(directory, raw, run_dir=root).with_complete_step(
        step_name=StepName.CONVERT, artifact_kind='image_raw', artifact_path=image)
    save_experiment_state(state)


def test_tuner_round_trip_and_close(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Apply tuner settings to the main GUI while preserving unrelated draft settings.
    """
    application()
    _write_current_run(tmp_path)
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    adapter.set_field_value(StepName.SEGMENT, "workers", 3)
    adapter.set_segment_channels([{"channel": "GFP", "user_settings": {"diameter": 19}}])
    window = FischMainWindow(adapter)
    window.user_name_edit.setText("Unsaved user")
    window._open_segmentation_tuner()
    tuner = window._segmentation_tuner
    assert isinstance(tuner, SegmentationTunerWindow)
    assert tuner._provided_settings is not None
    assert tuner._provided_settings.channels[0].user_settings["diameter"] == 19
    assert tuner.directory_browser.root_path == tmp_path
    assert tuner.windowModality() == Qt.WindowModality.WindowModal
    assert tuner.settings_panel.apply_button.text() == "Save current settings"
    chosen = SegmentSettings.model_validate({"channels": [{"channel": "GFP", "nuclear_channel": None,
                                                            "do_denoise": False, "user_settings": {"diameter": 31}}]})
    monkeypatch.setattr(tuner, "current_settings", lambda: chosen)
    tuner._apply_settings()
    assert tuner.isVisible()
    assert adapter.segment_channels()[0]["channel"] == "GFP"
    assert adapter.segment_channels()[0]["nuclear_channel"] == "None"
    assert adapter.field_value(StepName.SEGMENT, "workers") == 3
    assert adapter.user_name == "Unsaved user"
    assert window._editors[StepName.SEGMENT].channel_widgets[0]["user_settings.diameter"].value() == 31
    adapter.save_to_run_dir()
    reloaded = SettingsAdapter()
    reloaded.load(tmp_path / ".pipeline" / "settings.toml")
    settings = reloaded.segmentation_settings().channels[0]
    assert settings.user_settings["diameter"] == 31
    assert settings.nuclear_channel is None
    window.close()


def test_close_without_apply_leaves_settings_unchanged(tmp_path: Path) -> None:
    """
    Discard unsaved tuning without changing the main GUI draft.
    """
    application()
    _write_current_run(tmp_path)
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FischMainWindow(adapter)
    before = adapter.as_mapping()
    window._open_segmentation_tuner()
    active = window._segmentation_tuner
    assert isinstance(active, SegmentationTunerWindow)
    active.settings_panel.denoise.setChecked(False)
    active.close()
    assert adapter.as_mapping() == before
    window.close()


def test_drawmask_exposes_both_mask_types():
    application()
    viewer = MaskDrawingWindow()
    assert [viewer.tool_tabs.tabText(i) for i in range(2)] == ["Reference", "ROI"]
    from fisch.environment.constant import IMAGE_NAMES
    assert viewer.directory_browser.model.nameFilters() == [
        *IMAGE_NAMES, "proc_ref_*.tif", "proc_roi_*.tif"]
    viewer.close()


def test_invalid_apply_keeps_tuner_open():
    application()
    viewer = SegmentationTunerWindow()
    applied = []
    viewer.settings_applied.connect(applied.append)
    viewer.show()
    viewer._apply_settings()
    assert viewer.isVisible()
    assert applied == []
    viewer.close()


def test_tuner_styles_actions_and_preview_restores_overlay() -> None:
    """
    Fit the screen, share action styling, and restore the preview overlay.
    """
    application()
    viewer = SegmentationTunerWindow()

    available = viewer.screen().availableGeometry()
    assert viewer.width() == min(1800, available.width())
    assert viewer.height() == available.height()
    panel_layout = viewer.settings_panel.layout()
    assert isinstance(panel_layout, QVBoxLayout)
    channel_list_index = panel_layout.indexOf(viewer.channel_settings_list)
    assert channel_list_index == panel_layout.count() - 1
    assert viewer.channel_settings_list.maximumHeight() == 300
    actions_layout = viewer.preview_actions.layout()
    assert isinstance(actions_layout, QVBoxLayout)
    actions = []
    for index in range(3):
        item = actions_layout.itemAt(index)
        assert item is not None
        actions.append(item.widget())
    assert actions == [
        viewer.settings_panel.run_button,
        viewer.settings_panel.apply_button,
        viewer.close_button,
    ]
    viewer.show()
    QApplication.processEvents()
    for index, title in ((1, "Compartment"), (0, "Segmentation")):
        viewer.tool_tabs.setCurrentIndex(index)
        QApplication.processEvents()
        assert viewer.mode_label.text() == title
        title_left = viewer.mode_label.mapToGlobal(viewer.mode_label.rect().topLeft()).x()
        title_right = viewer.mode_label.mapToGlobal(viewer.mode_label.rect().topRight()).x()
        assert title_left > viewer.grayscale_lut_button.mapToGlobal(viewer.grayscale_lut_button.rect().topRight()).x()
        assert title_right < viewer.overlay_label.mapToGlobal(viewer.overlay_label.rect().topLeft()).x()
    assert viewer.preview_actions.mapToGlobal(
        viewer.preview_actions.rect().topLeft()).x() > viewer.lut_controls.mapToGlobal(
            viewer.lut_controls.rect().topRight()).x()
    assert viewer.settings_panel.run_button.width() == viewer.settings_panel.apply_button.width()
    assert "#d97706" in viewer.settings_panel.run_button.styleSheet()
    assert "#4f8f5b" in viewer.add_channel_button.styleSheet()
    assert "#16803b" in viewer.settings_panel.apply_button.styleSheet()
    assert "#e8a0a0" in viewer.close_button.styleSheet()
    assert viewer.close_button.text() == "Close window"
    viewer.show_mask.setChecked(False)
    viewer._run_preview()

    assert viewer.show_mask.isChecked()
    viewer.close()
