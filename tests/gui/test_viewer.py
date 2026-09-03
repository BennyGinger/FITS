from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from fits.environment.constant import FITS_ARRAY_NAME
from fits.gui.run_browser import DirectoryBrowser, RunDirectoryBrowser
from fits.gui.viewer.image_viewer import FitsImageViewer
from fits.gui.viewer.tools.reference_mask.settings_panel import ReferenceMaskPanel
from fits.gui.viewer.tools.roi_mask.settings_panel import RoiMaskPanel
from fits.gui.viewer.tools.segmentation.settings_panel import CellposeSettingsPanel
from fits.gui.viewer.window import FitsViewerWindow
from fits.settings.models import SegmentSettings


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def test_directory_browser_supports_a_reusable_title() -> None:
    _app()
    browser = DirectoryBrowser("Experiments directory contents")
    run_browser = RunDirectoryBrowser()

    assert browser.title_label.text() == "Experiments directory contents"
    assert run_browser.title_label.text() == "Run directory contents"


def test_cellpose_panel_returns_compact_user_settings() -> None:
    _app()
    panel = CellposeSettingsPanel()
    assert "automatic detection of cell boundaries" in (
        panel.layout().itemAt(1).widget().text())
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


def test_image_viewer_ignores_navigation_without_control() -> None:
    _app()
    viewer = FitsImageViewer()

    class MouseEvent:
        def __init__(self) -> None:
            self.ignored = False

        def modifiers(self):
            return Qt.KeyboardModifier.NoModifier

        def ignore(self) -> None:
            self.ignored = True

    drag_event = MouseEvent()
    wheel_event = MouseEvent()
    viewer.view_box.mouseDragEvent(drag_event)
    viewer.view_box.wheelEvent(wheel_event)

    assert drag_event.ignored is True
    assert wheel_event.ignored is True


def test_reference_panel_exposes_drawing_and_interpolation_controls() -> None:
    _app()
    panel = ReferenceMaskPanel()

    assert panel.interpolate.isChecked() is True
    assert panel.interpolation_title.text() == "Propagation"
    assert panel.interpolate.text() == "Propagate drawings"
    panel.set_available_axes("TCZYX", (4, 2, 3, 8, 8))
    panel.tool_combo.setCurrentIndex(panel.tool_combo.findData("triangle"))
    panel.interpolate.setChecked(True)

    assert panel.drawing_mode == "replace"
    assert panel.drawing_operation == "add"
    assert panel.drawing_tool == "triangle"
    panel.edit_mode.setChecked(True)
    assert panel.drawing_mode == "edit"
    assert panel.interpolation_axis.count() == 2
    assert panel.selected_interpolation_axis == "T"
    assert panel.interpolation_axis.isEnabled() is True
    assert panel.extrapolate_start.isEnabled() is True
    assert panel.live_preview.isEnabled() is True
    assert panel.live_preview.isCheckable()
    panel.live_preview.setChecked(True)
    assert panel.interpolation_preview_enabled is True
    assert panel.interpolation_axis.maximumWidth() == panel.CONTROL_WIDTH
    panel.interpolate.setChecked(False)
    assert panel.selected_interpolation_axis is None
    assert panel.interpolation_axis.isEnabled() is False
    assert panel.extrapolate_start.isEnabled() is False
    assert panel.extrapolate_end.isEnabled() is False
    assert panel.live_preview.isEnabled() is False
    assert panel.interpolation_preview_enabled is False
    assert panel.save_button.isEnabled() is False
    panel.label_edit.setText("wound")
    assert panel.save_button.isEnabled() is True


def test_hovered_numeric_setting_does_not_consume_wheel() -> None:
    _app()
    panel = ReferenceMaskPanel()

    class WheelEvent:
        accepted = False

        class Delta:
            def y(self) -> int:
                return 120

        def pixelDelta(self):
            return self.Delta()

        def angleDelta(self):
            return self.Delta()

        def accept(self) -> None:
            self.accepted = True

    event = WheelEvent()
    scroll_bar = panel.controls_scroll.verticalScrollBar()
    scroll_bar.setRange(0, 1000)
    scroll_bar.setValue(500)
    original_size = panel.brush_size.value()
    panel.brush_size.clearFocus()
    panel.brush_size.wheelEvent(event)

    assert event.accepted is True
    assert scroll_bar.value() == 380
    assert panel.brush_size.value() == original_size


def test_roi_panel_displays_an_editable_threshold_histogram() -> None:
    _app()
    panel = RoiMaskPanel()
    panel.set_available_axes("TYX", (3, 10, 10))
    assert panel.interpolate.isChecked() is False
    assert panel.interpolation_axis.isEnabled() is False
    panel.interpolate.setChecked(True)
    assert panel.interpolation_axis.isEnabled() is True
    assert panel.live_preview.isEnabled() is True
    assert panel.threshold_plot.maximumHeight() == 95
    assert panel.fill_holes_button.text() == "Fill"
    assert panel.minimum_object_size.value() == 50
    assert panel.remove_small_objects_button.text() == "Remove"
    changes: list[tuple[float, float]] = []
    panel.threshold_changed.connect(lambda low, high: changes.append((low, high)))

    panel.set_threshold_image(np.arange(100).reshape(10, 10))
    assert changes == []
    assert panel.current_minimum.value() == 0.0
    assert panel.current_maximum.value() == 99.0
    panel.threshold_region.setRegion((20, 80))
    panel._emit_threshold()

    assert changes[-1] == (20.0, 80.0)
    assert panel.current_minimum.value() == 20.0
    assert panel.current_maximum.value() == 80.0
    assert panel.full_threshold_range() == (0.0, 99.0)


def test_replace_drawing_replaces_canvas_and_commits_on_release() -> None:
    _app()
    viewer = FitsImageViewer()
    viewer.set_image(np.zeros((12, 12)))
    previous = np.zeros((12, 12), dtype=np.uint8)
    previous[9:11, 9:11] = 1
    viewer.set_drawing_mask(previous)
    viewer.set_mask_opacity(0.35)
    viewer.set_drawing_options("replace", "square", "add", 5)
    committed: list[np.ndarray] = []
    viewer.drawing_finished.connect(committed.append)

    viewer._start_drawing(2, 2)
    assert viewer.mask_item.opacity() == 0.8
    viewer._finish_drawing(6, 5)

    assert len(committed) == 1
    assert viewer.mask_item.opacity() == 0.35
    assert np.any(committed[0][2:7, 2:7])
    assert not np.any(committed[0][9:11, 9:11])

    restored = viewer.undo_drawing()
    assert restored is not None
    np.testing.assert_array_equal(restored, previous)


def test_edit_drawing_keeps_existing_mask_and_commits_on_release() -> None:
    _app()
    viewer = FitsImageViewer()
    viewer.set_image(np.zeros((12, 12)))
    existing = np.zeros((12, 12), dtype=np.uint8)
    existing[1, 1] = 1
    viewer.set_drawing_mask(existing)
    viewer.set_drawing_options("edit", "circle", "add", 5)
    changed: list[bool] = []
    committed: list[np.ndarray] = []
    viewer.drawing_changed.connect(lambda: changed.append(True))
    viewer.drawing_finished.connect(committed.append)

    viewer._start_drawing(6, 6)
    viewer._finish_drawing(8, 6)

    assert changed == [True]
    assert len(committed) == 1
    assert viewer.drawing_mask[1, 1] == 1
    assert np.any(viewer.drawing_mask[4:9, 4:9])


def test_image_viewer_draws_each_reference_shape() -> None:
    _app()
    viewer = FitsImageViewer()
    viewer.set_image(np.zeros((16, 16)))
    for tool in ("freehand", "line", "circle", "square", "triangle"):
        viewer.set_drawing_mask(np.zeros((16, 16), dtype=np.uint8))
        viewer.set_drawing_options("replace", tool, "add", 3)

        viewer._start_drawing(5, 4)
        viewer._continue_drawing(7, 7)
        viewer._finish_drawing(9, 10)

        assert np.any(viewer.drawing_mask)


def test_freehand_drawing_live_fills_its_enclosed_polygon() -> None:
    _app()
    viewer = FitsImageViewer()
    viewer.set_image(np.zeros((12, 12)))
    viewer.set_drawing_mask(np.zeros((12, 12), dtype=np.uint8))
    viewer.set_drawing_options("replace", "freehand", "add", 1)

    viewer._start_drawing(2, 2)
    viewer._continue_drawing(8, 2)
    viewer._continue_drawing(8, 8)

    assert viewer.drawing_mask[5, 5] == 1
    viewer._finish_drawing(2, 8)
    assert np.all(viewer.drawing_mask[3:8, 3:8])


def test_line_drawing_stays_open() -> None:
    _app()
    viewer = FitsImageViewer()
    viewer.set_image(np.zeros((12, 12)))
    viewer.set_drawing_mask(np.zeros((12, 12), dtype=np.uint8))
    viewer.set_drawing_options("edit", "line", "add", 1)

    viewer._start_drawing(2, 2)
    viewer._finish_drawing(8, 8)

    assert viewer.drawing_mask[5, 5] == 1
    assert viewer.drawing_mask[2, 8] == 0


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
    assert window.grayscale_lut_button.isChecked() is False
    assert ":checked" in window.grayscale_lut_button.styleSheet()
    assert window.image_viewer.histogram.maximumHeight() == 125
    assert "colour marker" in window.image_viewer.histogram.toolTip()
    assert "grayscale" in window.grayscale_lut_button.toolTip()
    assert "opacity" in window.mask_opacity.toolTip()
    assert "binary mask" in window.reference_mask_colour_button.toolTip()
    assert window.tool_tabs.count() == 1
    assert window.tool_tabs.widget(0) is window.settings_panel
    window.close()


def test_viewer_can_expose_binary_or_all_tools() -> None:
    _app()
    reference_window = FitsViewerWindow(tool="binary")
    full_window = FitsViewerWindow(tool="all")

    assert reference_window.tool_tabs.count() == 2
    assert reference_window.tool_tabs.widget(0) is reference_window.reference_panel
    assert reference_window.directory_browser.model.nameFilters() == [
        FITS_ARRAY_NAME, "fits_ref_*.tif", "fits_roi_*.tif"]
    assert reference_window.reference_mask_colour_button.isVisibleTo(reference_window)
    assert reference_window.segmentation_mask_colours.isVisibleTo(reference_window) is False
    assert full_window.tool_tabs.count() == 3
    assert full_window.tool_tabs.widget(0) is full_window.settings_panel
    assert full_window.tool_tabs.widget(1) is full_window.reference_panel
    assert full_window.tool_tabs.widget(2) is full_window.roi_panel
    reference_window.close()
    full_window.close()


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

    class FakeReferenceSession:
        def __init__(self, source_path: Path, *, reference_path=None) -> None:
            self.source_path = source_path
            self.reference_label = None
            self.loaded_channels = ()
            self.channel_labels = ("GFP", "DAPI")
            self.frame_count = 3
            self.plane_count = 2
            self.axes = "TCZYX"
            self.shape = (3, 2, 2, 8, 8)
            self.masks = np.zeros(self.shape, dtype=np.uint8)

        def mask_plane(self, frame_index: int, channel: str, z_index: int):
            channel_index = self.channel_labels.index(channel)
            return self.masks[frame_index, channel_index, z_index]

    monkeypatch.setattr(
        "fits.gui.viewer.window.ReferenceMaskSession",
        FakeReferenceSession,)
    class FakeRoiSession(FakeReferenceSession):
        def __init__(self, source_path: Path, *, roi_path=None) -> None:
            super().__init__(source_path)
            self.roi_label = None

    monkeypatch.setattr("fits.gui.viewer.window.RoiSession", FakeRoiSession)
    window = FitsViewerWindow(tmp_path, tool="all")
    emitted: list[SegmentSettings] = []
    window.settings_applied.connect(emitted.append)
    preview_requests: list[bool] = []
    monkeypatch.setattr(window, "_run_preview", lambda: preview_requests.append(True))

    window.tool_tabs.setCurrentWidget(window.reference_panel)
    window._open_source(source)
    assert window.tool_tabs.currentWidget() is window.reference_panel
    assert preview_requests == []
    window.tool_tabs.setCurrentWidget(window.settings_panel)
    window._run_preview()
    assert (window.image_viewer.drawing_item.acceptedMouseButtons()
            == Qt.MouseButton.NoButton)
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
    window.channel_combo.setFocus()
    QTest.keyClick(window.channel_combo, Qt.Key.Key_D)
    QTest.keyClick(window.channel_combo, Qt.Key.Key_A)
    QTest.keyClick(window.channel_combo, Qt.Key.Key_Z)
    QTest.keyClick(window.channel_combo, Qt.Key.Key_W)
    window.settings_panel.flow_threshold.setFocus()
    QTest.keyClick(window.settings_panel.flow_threshold, Qt.Key.Key_R)

    assert window.frame_slider.value() == 1
    assert window.z_slider.value() == 1
    assert window.channel_combo.currentText() == "DAPI"
    assert window.show_mask.isChecked() is False
    assert preview_requests == [True, True, True]

    window.channel_combo.setCurrentText("DAPI")
    window.settings_panel.denoise.setCheckState(Qt.CheckState.Unchecked)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_S)

    assert window.frame_slider.maximum() == 2
    assert window.z_slider.maximum() == 1
    assert emitted[0].channel_to_segment == ["DAPI"]
    assert emitted[0].do_denoise is False
    window.close()


def test_reference_tab_commits_raster_edits_and_persists_drawings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    source = experiment / FITS_ARRAY_NAME
    source.touch()

    class FakeSegmentationSession:
        def __init__(self, source_path: Path, *, segment_settings=None) -> None:
            self.source_path = source_path
            self.segment_settings = segment_settings or SegmentSettings(
                channel_to_segment=["GFP"], user_settings={"model_type": "cyto3"})
            self.channel_labels = ("GFP", "RFP")
            self.frame_count = 3
            self.plane_count = 1
            self.axes = "TCYX"
            self.shape = (3, 2, 12, 12)

        def display_frame(self, frame_index: int, channel: str, z_index: int):
            return np.full((12, 12), frame_index)

        def set_segment_settings(self, settings: SegmentSettings) -> None:
            self.segment_settings = settings

        def load_cached_preview(self, *args, **kwargs):
            return None

        def close(self) -> None:
            pass

    class FakeReferenceSession:
        def __init__(self, source_path: Path, *, reference_path=None) -> None:
            self.source_path = source_path
            self.reference_label = None
            self.loaded_channels = ()
            self.channel_labels = ("GFP", "RFP")
            self.frame_count = 3
            self.plane_count = 1
            self.axes = "TCYX"
            self.shape = (3, 2, 12, 12)
            self.masks = np.zeros(self.shape, dtype=np.uint8)
            self.saved_mask = None
            self.existing_channels = ()
            self.history = []

        def _channel(self, channel: str) -> int:
            return self.channel_labels.index(channel)

        def mask_plane(self, frame_index: int, channel: str, z_index: int):
            return self.masks[frame_index, self._channel(channel)].copy()

        def set_mask_plane(self, mask, *, frame_index, channel, z_index) -> None:
            self.masks[frame_index, self._channel(channel)] = mask

        def apply_display_edit(
                self, mask, *, comparison_mask, frame_index, channel, z_index) -> None:
            current = self.mask_plane(frame_index, channel, z_index)
            self.history.append((frame_index, channel, z_index, current.copy()))
            changed = np.asarray(mask) != np.asarray(comparison_mask)
            current[changed] = np.asarray(mask)[changed]
            self.set_mask_plane(
                current, frame_index=frame_index, channel=channel, z_index=z_index)

        def undo_display_edit(self, **kwargs):
            if not self.history:
                return None
            frame_index, channel, z_index, mask = self.history.pop()
            self.set_mask_plane(
                mask, frame_index=frame_index, channel=channel, z_index=z_index)
            return mask

        def clear_mask_plane(self, *, frame_index, channel, z_index) -> None:
            self.masks[frame_index, self._channel(channel)] = 0

        def save(self, label: str, **kwargs):
            self.saved_mask = self.masks.copy()
            return self.source_path.with_name(f"fits_ref_{label}.tif")

        def saved_channels(self, label: str):
            return self.existing_channels

    monkeypatch.setattr(
        "fits.gui.viewer.window.SegmentationTuningSession",
        FakeSegmentationSession,)
    monkeypatch.setattr(
        "fits.gui.viewer.window.ReferenceMaskSession",
        FakeReferenceSession,)
    class FakeRoiSession(FakeReferenceSession):
        def __init__(self, source_path: Path, *, roi_path=None) -> None:
            super().__init__(source_path)
            self.roi_label = None

    monkeypatch.setattr("fits.gui.viewer.window.RoiSession", FakeRoiSession)
    window = FitsViewerWindow(tmp_path, tool="all")
    monkeypatch.setattr(window, "_run_preview", lambda: None)
    window._open_source(source)
    reference_session = window._reference_session
    window.tool_tabs.setCurrentWidget(window.reference_panel)
    window.reference_panel.edit_mode.setChecked(True)
    assert (window.image_viewer.drawing_item.acceptedMouseButtons()
            == (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton))
    window.reference_panel.tool_combo.setCurrentIndex(
        window.reference_panel.tool_combo.findData("circle"))
    window.reference_panel.live_preview.setChecked(True)

    window.image_viewer._start_drawing(4, 4)
    assert window.reference_panel.live_preview.isChecked() is False
    window.image_viewer._finish_drawing(6, 4)
    assert reference_session is window._reference_session
    assert reference_session is not None
    assert np.any(reference_session.masks[0, 0])

    expected = reference_session.masks[0, 0].copy()
    window.image_viewer._start_drawing(1, 1)
    window.image_viewer._finish_drawing(1, 1)
    assert not np.array_equal(reference_session.masks[0, 0], expected)
    window._undo_reference_drawing()
    np.testing.assert_array_equal(reference_session.masks[0, 0], expected)
    window.frame_slider.setValue(1)
    window.frame_slider.setValue(0)
    np.testing.assert_array_equal(window.image_viewer.drawing_mask, expected)

    window.image_viewer._start_drawing(8, 8, "erase")
    window.image_viewer._finish_drawing(9, 8)
    assert np.any(reference_session.masks[0, 0])
    information_messages: list[str] = []
    reference_session.existing_channels = ("RFP",)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, message: information_messages.append(message),)
    window.reference_panel.label_edit.setText("test")
    window._save_reference_mask()
    assert reference_session.saved_mask is not None
    assert np.any(reference_session.saved_mask)
    assert "GFP reference channel will be added" in information_messages[0]
    window.tool_tabs.setCurrentWidget(window.settings_panel)
    assert reference_session is window._reference_session
    window.close()
