"""Viewer selection, rectangle gestures, preview, and the cropped-save workflow."""

from time import monotonic
from threading import Event
from typing import cast

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO
from PySide6.QtCore import QEvent, QPoint, QPointF, QThread, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QSpinBox, QWidget

from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_TRACK
from fits.gui.viewer.tracking.window import TrackingViewerWindow


_APP: QApplication | None = None


def app() -> QApplication:
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    return _APP


def wait_until(condition, window) -> None:
    deadline = monotonic() + 5
    while not condition():
        app().processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, window.status_label.text()


@pytest.fixture
def tracking(tmp_path):
    raw = np.arange(4 * 2 * 100 * 120, dtype=np.float32).reshape(4, 2, 100, 120)
    input_path = tmp_path / "input.tif"
    tifffile.imwrite(input_path, raw, imagej=True, metadata={"axes": "TCYX"})
    reader = FitsIO.from_path(input_path)
    source = reader.save_array(raw, channel_labels=("GFP", "RFP"),
                                output_path=tmp_path / FITS_ARRAY_NAME)
    masks = np.zeros((4, 100, 120), dtype=np.uint16)
    for frame in range(4):
        masks[frame, 20:25, 10 + frame * 10:15 + frame * 10] = 7
        masks[frame, 50:55, 60:65] = 11
        masks[frame, 70:75, 90:95] = 23
    path = FitsIO.from_path(source).save_array(
        masks, export_channels=("GFP",), output_path=tmp_path / FITS_MASK_TRACK)
    return path, raw


@pytest.fixture
def window(tracking):
    app()
    window = TrackingViewerWindow(tracking_path=tracking[0], editing_enabled=False,
                                   selection_enabled=True)
    window.show()
    wait_until(lambda: window._trajectory_thread is None
               and window._trajectory_ready_key == window._trajectory_key(), window)
    try:
        yield window
    finally:
        window.close()


def image_point(window, x, y) -> QPoint:
    scene = window.image_viewer.view_box.mapViewToScene(QPointF(x, y))
    return cast(QPoint, window.image_viewer.canvas.mapFromScene(scene))


def drag(window, start, end, modifiers=Qt.KeyboardModifier.NoModifier):
    viewport = cast(QWidget, window.image_viewer.canvas.viewport())
    first, last = image_point(window, *start), image_point(window, *end)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, modifiers, first)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(last),
                        QPointF(viewport.mapToGlobal(last)), Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton, modifiers)
    app().sendEvent(viewport, event)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, modifiers, last)
    app().processEvents()


def test_viewer_selection_is_unlimited_and_synced_with_ctrl_clicks(window):
    assert window.diameter_reference is None
    assert isinstance(window.track_id_input, QLineEdit)
    window.track_id_input.setText("7, 11, 23, 7")
    window.select_track_button.click()
    assert window._selected_track_ids == [7, 11, 23]
    assert window.track_id_input.text() == "7, 11, 23"
    assert len(window._track_id_items) == 3
    window.track_path_display_mode.setCurrentIndex(window.track_path_display_mode.findData("selected"))
    assert sum(item.isVisible() for item in window._selected_path_items) == 3
    window.crop_panel.enabled.setChecked(True)
    viewport = cast(QWidget, window.image_viewer.canvas.viewport())
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     image_point(window, 12, 22))
    assert window._selected_track_ids == [11, 23]
    assert window.track_id_input.text() == "11, 23"
    assert len(window._track_id_items) == 2
    window.track_id_input.setText("11, missing")
    window.select_track_button.click()
    assert window._selected_track_ids == [11, 23]
    window.track_id_input.setText("7, 999")
    window.select_track_button.click()
    assert window._selected_track_ids == [11, 23]
    assert "999" in window.status_label.text()
    window._clear_track_selection()
    assert window.track_id_input.text() == ""


def test_ctrl_drag_selects_current_frame_centroids_and_drops_rectangle(window):
    panel = window.crop_panel
    control = Qt.KeyboardModifier.ControlModifier
    viewport = cast(QWidget, window.image_viewer.canvas.viewport())
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, control,
                     image_point(window, 12, 22))
    assert window._selected_track_ids == [7]
    before = window.image_viewer.view_box.viewRange()
    drag(window, (5, 15), (70, 65), control)
    assert window._selected_track_ids == [7, 11]
    assert window.track_id_input.text() == "7, 11"
    assert not panel.selection_rectangle.isVisible()
    assert panel.bounds is None
    assert window.image_viewer.view_box.viewRange() == before

    window.frame_slider.setValue(1)
    drag(window, (5, 15), (18, 30), control)
    assert window._selected_track_ids == []  # Cell 7 moved out of the rectangle.
    assert not panel.selection_rectangle.isVisible()


def test_crop_rectangle_selects_cells_and_crop_refits_selected_tracks(window):
    panel = window.crop_panel
    panel.enabled.setChecked(True)
    drag(window, (5, 15), (70, 65))
    assert panel.bounds is not None
    assert panel.bounds[0] <= 5 and panel.bounds[1] <= 15
    assert panel.bounds[2] >= 70 and panel.bounds[3] >= 65
    assert window._selected_track_ids == [7, 11]
    drag(window, (5, 15), (18, 30), Qt.KeyboardModifier.ControlModifier)
    assert panel.bounds is not None and panel.bounds[2] <= 19
    assert panel.rectangle.isVisible()
    assert window._selected_track_ids == [7]
    panel.crop_button.click()
    wait_until(lambda: window._crop_thread is None, window)
    assert panel.bounds == (8, 19, 47, 26)


def test_editor_retains_two_cell_limit_and_has_no_crop_panel(tracking):
    app()
    editor = TrackingViewerWindow(tracking_path=tracking[0])
    try:
        assert isinstance(editor.track_id_input, QSpinBox)
        assert editor.crop_panel is None
        assert editor.diameter_reference is not None
        for track in (7, 11, 23):
            editor._toggle_track_selection(track)
        assert editor._selected_track_ids == [7, 11]
    finally:
        editor.close()


def test_automatic_crop_uses_all_selected_cells_and_preview_only_changes_zoom(window):
    panel = window.crop_panel
    window.track_id_input.setText("7, 11, 23")
    window.select_track_button.click()
    panel.enabled.setChecked(True)
    assert panel.bounds is None
    panel.crop_button.click()
    wait_until(lambda: window._crop_thread is None, window)
    assert panel.bounds == (5, 17, 100, 78)
    assert panel.width_input.value() == 95
    assert panel.height_input.value() == 61
    assert panel.rectangle.isVisible()
    assert panel.rectangle.pen().color() == QColor("yellow")
    home = window.image_viewer.view_box.viewRange()
    panel.preview_button.click()
    assert panel.preview_button.isChecked()
    assert window.image_viewer.view_box.viewRange() != home
    panel.preview_button.click()
    ranges = window.image_viewer.view_box.viewRange()
    assert ranges[0][0] <= 0 and ranges[0][1] >= 120
    assert ranges[1][0] <= 0 and ranges[1][1] >= 100
    panel.preview_button.click()
    window.image_viewer.home_button.click()
    assert not panel.preview_button.isChecked()
    ranges = window.image_viewer.view_box.viewRange()
    assert ranges[0][0] <= 0 and ranges[0][1] >= 120
    assert ranges[1][0] <= 0 and ranges[1][1] >= 100
    assert panel.bounds == (5, 17, 100, 78)


def test_rectangle_draw_move_edge_corner_resize_and_numeric_sizes(window, monkeypatch):
    panel = window.crop_panel
    panel.enabled.setChecked(True)
    drag(window, (10.25, 12.25), (70.75, 62.75))
    assert panel.bounds == (10, 12, 71, 63)
    assert (panel.width_input.value(), panel.height_input.value()) == (61, 51)
    drag(window, (40, 38), (45, 45))
    assert panel.bounds == (15, 19, 76, 70)
    drag(window, (76, 40), (90, 40))
    assert panel.bounds == (15, 19, 90, 70)
    drag(window, (15, 19), (10, 12))
    assert panel.bounds == (10, 12, 90, 70)
    panel.width_input.setValue(60)
    panel.height_input.setValue(40)
    assert panel.bounds == (20, 21, 80, 61)
    monkeypatch.setattr("fits.gui.viewer.tracking.crop.QColorDialog.getColor",
                        lambda *args: QColor("cyan"))
    panel.color_button.click()
    assert panel.rectangle.pen().color() == QColor("cyan")
    panel.enabled.setChecked(False)
    assert not panel.rectangle.isVisible()


def test_empty_selection_guidance_and_manual_rectangle_has_no_padding(window, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[-1]))
    panel = window.crop_panel
    panel.enabled.setChecked(True)
    panel.crop_button.click()
    assert len(messages) == 1
    assert "Select at least one cell or draw a rectangle" in messages[0]
    window.save_display_button.click()
    assert len(messages) == 2
    assert window._save_thread is None
    drag(window, (20.25, 20.25), (50.75, 60.75))
    assert panel.bounds == (20, 20, 51, 61)
    panel.crop_button.click()
    assert panel.bounds == (20, 20, 51, 61)
    assert len(messages) == 2


def test_saving_crops_in_home_and_preview_but_not_when_mode_is_off(window, tracking, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[-1]))
    panel = window.crop_panel
    panel.enabled.setChecked(True)
    panel.set_bounds((5, 10, 85, 80))
    for label, preview, enabled in (("home", False, True), ("preview", True, True), ("whole", False, False)):
        panel.enabled.setChecked(enabled)
        panel.preview_button.setChecked(preview)
        window.display_label_edit.setText(label)
        window.save_display_button.click()
        wait_until(lambda: window._save_thread is None, window)
        assert errors == []
        suffix = "_cropped" if enabled else ""
        output = tmp_path / f"fits_track_overlay_{label}{suffix}.tif"
        expected = tracking[1][..., 10:80, 5:85] if enabled else tracking[1]
        np.testing.assert_array_equal(tifffile.imread(output), expected)
        meta = FitsIO.from_path(output).metadata.custom_metadata
        assert ("spatial_crops" in meta) == enabled


def test_automatic_fitting_keeps_navigation_responsive_and_discards_stale_selection(window, monkeypatch):
    started, release = Event(), Event()
    original = window._tracking_session.tracked_frame

    def slow_read(*args):
        if QThread.currentThread() != app().thread() and not started.is_set():
            started.set()
            assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(window._tracking_session, "tracked_frame", slow_read)
    window._toggle_track_selection(7)
    panel = window.crop_panel
    panel.enabled.setChecked(True)
    try:
        panel.crop_button.click()
        wait_until(started.is_set, window)
        window.frame_slider.setValue(1)
        assert window.frame_slider.value() == 1
        assert not window.image_viewer._loading_visible
        window._toggle_track_selection(23)
        release.set()
        wait_until(lambda: window._crop_thread is None, window)
        assert panel.bounds is None
        assert "changed" in window.status_label.text()
        panel.crop_button.click()
        wait_until(lambda: window._crop_thread is None, window)
        assert panel.bounds == (5, 17, 100, 78)
    finally:
        release.set()
