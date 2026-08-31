from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fits.environment.constant import FITS_ARRAY_NAME
from fits.gui.run_browser import DirectoryBrowser, RunDirectoryBrowser
from fits.gui.viewer.image_viewer import FitsImageViewer
from fits.gui.viewer.tools.segmentation.settings_panel import CellposeSettingsPanel
from fits.gui.viewer.window import FitsViewerWindow
from fits.settings.models import SegmentSettings


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_directory_browser_supports_a_reusable_title() -> None:
    _app()
    browser = DirectoryBrowser("Experiments directory contents")
    run_browser = RunDirectoryBrowser()

    assert browser.title_label.text() == "Experiments directory contents"
    assert run_browser.title_label.text() == "Run directory contents"


def test_cellpose_panel_returns_compact_user_settings() -> None:
    _app()
    panel = CellposeSettingsPanel()
    settings = SegmentSettings(
        channel_to_segment=["GFP"],
        nuclear_channel="DAPI",
        do_denoise=False,
        user_settings={"pretrained_model": "/tmp/custom_model",
                       "diameter": 24,
                       "do_3D": True,},)

    panel.set_settings(settings)
    panel.set_channels(("GFP", "DAPI"), settings.nuclear_channel)

    assert panel.user_settings()["pretrained_model"] == "/tmp/custom_model"
    assert panel.user_settings()["diameter"] == 24
    assert panel.user_settings()["do_3D"] is True
    assert panel.selected_nuclear_channel == "DAPI"
    assert panel.denoise.isChecked() is False
    assert panel.builtin_model.count() > 0
    assert panel.cellprob_threshold.minimum() == -6.0
    assert panel.cellprob_threshold.maximum() == 6.0
    assert panel.flow_threshold.toolTip()


def test_cellpose_panel_disables_volume_settings_without_z_stack() -> None:
    _app()
    panel = CellposeSettingsPanel()
    panel.do_3d.setChecked(True)
    panel.stitch_threshold.setValue(0.5)
    panel.anisotropy.setValue(2.0)

    panel.set_3d_available(False)

    assert panel.do_3d.isChecked() is False
    assert panel.stitch_threshold.value() == 0.0
    assert panel.anisotropy.value() == 0.0
    assert panel.do_3d.isEnabled() is False
    assert panel.stitch_threshold.isEnabled() is False
    assert panel.anisotropy.isEnabled() is False


def test_image_viewer_displays_image_and_mask() -> None:
    _app()
    viewer = FitsImageViewer()

    viewer.set_image(np.arange(16).reshape(4, 4))
    viewer.set_mask(np.asarray([[0, 0, 1, 1]] * 4))

    assert viewer.image_item.image.shape == (4, 4)
    assert viewer.mask_item.image.shape == (4, 4, 4)


def test_image_viewer_uses_channel_colour_mapping() -> None:
    _app()
    viewer = FitsImageViewer()

    viewer.set_channel_lut("GFP")
    assert viewer.lut_color == "green"

    viewer.set_channel_lut("unknown channel")
    assert viewer.lut_color == "gray"


def test_lut_controls_levels_and_removes_selected_marker() -> None:
    _app()
    viewer = FitsImageViewer()
    image = np.arange(100, dtype=float).reshape(10, 10)
    image[-1, -1] = 10000
    viewer.set_image(image)

    viewer.auto_scale()
    auto_levels = viewer.histogram.getLevels()
    viewer.full_range()
    assert auto_levels[1] < 10000
    assert viewer.histogram.getLevels() == (0.0, 10000.0)

    marker = viewer.histogram.item.gradient.addTick(0.5)
    assert viewer._remove_gradient_marker(marker) is True
    assert marker not in viewer.histogram.item.gradient.ticks


def test_viewer_browser_filters_non_fits_artifacts() -> None:
    _app()
    window = FitsViewerWindow()

    assert window.directory_browser.model.nameFilters() == [FITS_ARRAY_NAME]
    assert window.directory_browser.model.nameFilterDisables() is False
    assert window.colour_lut_button.isChecked() is True
    window.close()


def test_viewer_opens_a_source_and_emits_complete_settings(tmp_path: Path,
                                                          monkeypatch,
                                                          ) -> None:
    app = _app()
    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    source = experiment / FITS_ARRAY_NAME
    source.touch()

    class FakeSession:
        def __init__(self, source_path: Path, *, segment_settings=None) -> None:
            self.source_path = source_path
            self.segment_settings = segment_settings or SegmentSettings(
                channel_to_segment=["GFP"],
                user_settings={"model_type": "cyto3"},)
            self.channel_labels = ("GFP", "DAPI")
            self.frame_count = 3
            self.plane_count = 2
            self.axes = "TCZYX"
            self.shape = (3, 2, 2, 8, 8)

        def display_frame(self, frame_index: int, channel: str, z_index: int):
            return np.full((8, 8), frame_index + z_index)

        def set_segment_settings(self, settings: SegmentSettings) -> None:
            self.segment_settings = settings

        def load_cached_preview(self, *args, **kwargs):
            return None

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "fits.gui.viewer.window.SegmentationTuningSession",
        FakeSession,)
    window = FitsViewerWindow(tmp_path)
    emitted: list[SegmentSettings] = []
    window.settings_applied.connect(emitted.append)
    preview_requests: list[bool] = []
    monkeypatch.setattr(window, "_run_preview", lambda: preview_requests.append(True))

    window._open_source(source)
    window.image_viewer.set_display_levels((10.0, 20.0))
    window.frame_slider.setValue(1)
    assert window.image_viewer.display_levels == (10.0, 20.0)
    window.channel_combo.setCurrentText("DAPI")
    window.channel_combo.setCurrentText("GFP")
    assert window.image_viewer.display_levels == (10.0, 20.0)
    window.frame_slider.setValue(0)
    window.show()
    window.activateWindow()
    app.processEvents()
    window.image_viewer.setFocus()

    QTest.keyClick(window.image_viewer, Qt.Key.Key_Right)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_Up)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_C)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_X)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_R)
    window.settings_panel.flow_threshold.setFocus()
    QTest.keyClick(window.settings_panel.flow_threshold, Qt.Key.Key_R)

    assert window.frame_slider.value() == 1
    assert window.z_slider.value() == 1
    assert window.channel_combo.currentText() == "DAPI"
    assert window.settings_panel.show_mask.isChecked() is False
    assert preview_requests == [True, True, True]

    window.channel_combo.setCurrentText("DAPI")
    window.settings_panel.denoise.setCheckState(Qt.CheckState.Unchecked)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_S)

    assert window.frame_slider.maximum() == 2
    assert window.z_slider.maximum() == 1
    assert emitted[0].channel_to_segment == ["DAPI"]
    assert emitted[0].do_denoise is False
    window.close()
