"""Area geometry, source intensities and live time/Z profile integration."""

import os
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Any, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import tifffile
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from fisch.gui.viewer.common.area_selection import AreaSelection
from fisch.gui.viewer.background import BackgroundTunerWindow
from fisch.gui.viewer.tracking import TrackingViewerWindow
from fisch.settings.models import BGSubSettings
from fisch.interaction import FischImageSession
from fisch.tasks.bg_sub_tuning import BackgroundTuningSession


_APP: QApplication | None = None


@pytest.fixture(autouse=True)
def app() -> None:
    """
    Retain one Qt application throughout these real-viewer integration tests.
    """
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """
    Write distinct time and Z offsets over the same spatially varying pixels.
    """
    path = tmp_path / "proc_array.tif"
    base = np.random.default_rng(42).integers(100, 400, (24, 32), dtype=np.uint16)
    pixels = np.stack([np.stack([base + t * 100 + z * 10 for z in range(2)]) for t in range(3)])
    tifffile.imwrite(path, pixels, imagej=True, metadata={"axes": "TZYX"})
    return path


def _wait(predicate: Callable[[], bool]) -> None:
    """
    Process queued Qt work until a worker and its latest request have finished.
    """
    deadline = monotonic() + 15
    while not predicate():
        QTest.qWait(10)
        assert monotonic() < deadline, "Profile or preview did not finish"


def _drag(window: TrackingViewerWindow, start: tuple[float, float], end: tuple[float, float]) -> None:
    """
    Deliver real viewport gestures in image coordinates, including held-button state.
    """
    viewer = window.image_viewer
    viewport = cast(QWidget, viewer.canvas.viewport())
    first = cast(QPoint, viewer.canvas.mapFromScene(viewer.view_box.mapViewToScene(cast(Any, QPointF(*start)))))
    last = cast(QPoint, viewer.canvas.mapFromScene(viewer.view_box.mapViewToScene(cast(Any, QPointF(*end)))))
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(last), QPointF(viewport.mapToGlobal(last)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, event)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, last)
    QApplication.processEvents()


def test_shape_means_use_actual_interiors_and_signed_pixels() -> None:
    """
    Exclude bounding-box corners for ellipses and polygons without display clipping.
    """
    pixels = np.full((10, 10), -3.5, dtype=np.float32)
    pixels[0, 0] = 1000
    rectangle = AreaSelection("Rectangle", ((0, 0), (10, 10)))
    ellipse = AreaSelection("Ellipse", ((0, 0), (10, 10)))
    polygon = AreaSelection("Polygon", ((5, 0), (10, 10), (0, 10)))
    assert rectangle.mean(pixels) > 0
    assert ellipse.mean(pixels) == -3.5
    assert polygon.mean(pixels) == -3.5
    assert np.isnan(AreaSelection("Rectangle", ((20, 20), (25, 25))).mean(pixels))


def test_file_viewer_draw_move_clear_and_live_time_z_profile(source: Path) -> None:
    """
    Draw by default on raw files, move the area, and update both profile dimensions.
    """
    raw = source.with_name("input.tif")
    raw.write_bytes(source.read_bytes())
    window = TrackingViewerWindow(tracking_path=raw, editing_enabled=False)
    window.show()
    QApplication.processEvents()
    measurement = window.measurement
    assert measurement is not None
    try:
        _drag(window, (3, 3), (15, 15))
        area = measurement.drawing.selection
        assert area is not None and area.kind == "Rectangle"
        assert window.image_viewer.pixel_readout.single_tag.text() == "Mean"
        measurement.profile_button.click()
        dialog = measurement.dialog
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive() and len(dialog.plot.listDataItems()) == 1)
        x, y = dialog.plot.listDataItems()[0].getData()
        np.testing.assert_array_equal(x, [1, 2, 3])
        np.testing.assert_allclose(np.diff(y), 100)
        _drag(window, (9, 9), (12, 11))
        assert measurement.drawing.selection != area
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive())
        assert dialog._request is not None
        assert dialog._request.area == measurement.drawing.selection
        dialog.axis.setCurrentIndex(1)
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive())
        x, y = dialog.plot.listDataItems()[0].getData()
        np.testing.assert_array_equal(x, [1, 2])
        np.testing.assert_allclose(np.diff(y), 10)
        measurement.drawing.clear()
        assert not measurement.profile_button.isEnabled()
        assert not dialog.plot.listDataItems()
        assert window.image_viewer.pixel_readout.single_tag.text() == ""
    finally:
        window.close()


def test_background_area_before_after_preview_and_two_labelled_profile_curves(source: Path,
                                                                            monkeypatch: pytest.MonkeyPatch,
                                                                            ) -> None:
    """
    Keep drawing independent of preview, then expose original and processed means.
    """
    monkeypatch.setattr("fisch.gui.viewer.background.window.confirm_discard_tuner_changes", lambda *args: True)
    window = BackgroundTunerWindow(source.parent, settings=BGSubSettings(size=3))
    window.show()
    QApplication.processEvents()
    try:
        measurement = window.measurement
        measurement.drawing.set_rectangle((3, 3, 18, 18))
        assert window._thread is None
        assert window.image_viewer.pixel_readout.single_tag.text() == "Mean"
        window.run_button.click()
        _wait(lambda: window._thread is None)
        assert window.image_viewer.pixel_readout._measurements is not None
        assert [name for name, _ in window.image_viewer.pixel_readout._measurements] == ["Original", "BGSub"]
        measurement.profile_button.click()
        dialog = measurement.dialog
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive() and len(dialog.plot.listDataItems()) == 2)
        assert [item.name() for item in dialog.plot.listDataItems()] == ["Original", "BGSub"]
        window.settings_panel.threshold.setValue(0.2)
        assert window.image_viewer.pixel_readout.single_tag.text() == "Mean"
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive())
        assert len(dialog.plot.listDataItems()) == 1
    finally:
        window.close()


def test_profile_disables_singleton_axes_and_respects_default_lut_width(source: Path) -> None:
    """
    Keep profiles unavailable for 2D images and preserve the existing LUT allocation.
    """
    tifffile.imwrite(source, np.ones((24, 32), dtype=np.uint16), metadata={"axes": "YX"})
    window = BackgroundTunerWindow(source.parent)
    try:
        window.measurement.drawing.set_rectangle((2, 2, 10, 10))
        assert not window.measurement.profile_button.isEnabled()
        assert window.image_viewer.pixel_readout.title() == "Intensities"
        window.resize(1700, 1000)
        window.show()
        QApplication.processEvents()
        profile = window.measurement.profile_button
        assert window.auto_scale_button.size() == window.full_range_button.size() == profile.size()
        assert window.auto_scale_button.font() == profile.font()
        controls = window.lut_controls
        histogram = cast(QWidget, window.image_viewer.histogram)
        heights = []
        sizes = []
        action_sizes = []
        button_sizes = []
        control_positions = []
        save_positions = []
        for footer_height in (120, 260, 150):
            window.right_splitter.setSizes([1000 - footer_height, footer_height])
            QApplication.processEvents()
            auto = window.auto_scale_button.mapTo(controls, window.auto_scale_button.rect().topLeft())
            profile_top = profile.mapTo(controls, profile.rect().topLeft())
            graph = histogram.mapTo(controls, histogram.rect().topLeft())
            readout = window.image_viewer.pixel_readout
            box = readout.mapTo(controls, readout.rect().topLeft())
            assert auto.y() == profile_top.y()
            assert 0 <= graph.y() - auto.y() - window.auto_scale_button.height() <= 3
            assert box.y() == graph.y()
            assert readout.height() == histogram.height()
            heights.append(readout.height())
            sizes.append((controls.width(), controls.height()))
            action_sizes.append(window.viewer_actions.size())
            button_sizes.append(window.save_button.size())
            control_positions.append(controls.mapTo(window, controls.rect().topLeft()))
            save_positions.append(window.save_button.mapTo(window, window.save_button.rect().topLeft()))
            assert controls.rect().contains(readout.geometry())
        assert len(set(heights)) == 1
        assert sizes == [(560, 125)] * 3
        assert all(position == control_positions[0] for position in control_positions)
        assert all(position == save_positions[0] for position in save_positions)
        assert all(size == action_sizes[0] for size in action_sizes)
        assert all(size == button_sizes[0] for size in button_sizes)
        window.resize(1900, 1100)
        window.main_splitter.setSizes([550, 1300])
        QApplication.processEvents()
        assert (controls.width(), controls.height()) == (560, 125)
        assert window.viewer_actions.size() == action_sizes[0]
        assert window.save_button.size() == button_sizes[0]
    finally:
        window.close()


@pytest.mark.parametrize("kind", ["Ellipse", "Polygon"])
def test_ellipse_and_polygon_can_be_drawn_moved_and_reshaped(source: Path, kind: str) -> None:
    """
    Keep nonrectangular outlines persistent and update their measurement geometry.
    """
    raw = source.with_name("input.tif")
    raw.write_bytes(source.read_bytes())
    window = TrackingViewerWindow(tracking_path=raw, editing_enabled=False)
    window.show()
    QApplication.processEvents()
    measurement = window.measurement
    assert measurement is not None
    panel = measurement.drawing
    panel.shape_combo.setCurrentText(kind)
    try:
        if kind == "Ellipse":
            _drag(window, (3, 3), (19, 19))
        else:
            viewport = cast(QWidget, window.image_viewer.canvas.viewport())
            for x, y in [(3, 3), (19, 3), (11, 19)]:
                point = cast(QPoint, window.image_viewer.canvas.mapFromScene(
                    window.image_viewer.view_box.mapViewToScene(cast(Any, QPointF(x, y)))))
                QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        area = panel.selection
        assert area is not None and area.kind == kind
        _drag(window, (11, 10), (13, 12))
        moved = panel.selection
        assert moved is not None and moved != area
        if kind == "Ellipse":
            _drag(window, (21, 13), (24, 13))
        else:
            x, y = moved.points[0]
            _drag(window, (x, y), (x + 2, y + 1))
        assert panel.selection is not None and panel.selection != moved
        assert panel.selection.kind == kind
        assert measurement.viewer.pixel_readout.single_tag.text() == "Mean"
    finally:
        window.close()


@pytest.mark.parametrize("axes", ["TYX", "ZYX"])
def test_profile_axis_dropdown_disables_absent_dimension(source: Path, axes: str) -> None:
    """
    Choose the available dimension automatically and gray out its absent alternative.
    """
    tifffile.imwrite(source, np.ones((3, 24, 32), dtype=np.uint16), imagej=True, metadata={"axes": axes})
    window = BackgroundTunerWindow(source.parent)
    try:
        window.measurement.drawing.set_rectangle((2, 2, 10, 10))
        assert window.measurement.profile_button.isEnabled()
        dialog = window.measurement.dialog
        assert dialog.axis.currentData() == axes[0]
        model = dialog.axis.model()
        assert bool(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEnabled) == (axes[0] == "T")
        assert bool(model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsEnabled) == (axes[0] == "Z")
    finally:
        window.close()


def test_profile_uses_calibrated_time_when_available(source: Path) -> None:
    """
    Use acquisition seconds instead of frame numbers when TIFF timing is present.
    """
    pixels = np.arange(3, dtype=np.uint16)[:, None, None] * np.ones((3, 24, 32), dtype=np.uint16)
    tifffile.imwrite(source, pixels, imagej=True, metadata={"axes": "TYX", "finterval": 2.5})
    window = BackgroundTunerWindow(source.parent)
    window.show()
    QApplication.processEvents()
    try:
        window.measurement.drawing.set_rectangle((2, 2, 10, 10))
        window.measurement.profile_button.click()
        dialog = window.measurement.dialog
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive() and len(dialog.plot.listDataItems()) == 1)
        x, y = dialog.plot.listDataItems()[0].getData()
        np.testing.assert_array_equal(x, [0, 2.5, 5])
        np.testing.assert_array_equal(y, [0, 1, 2])
        assert dialog.axis.itemText(0) == "Time (s)"
    finally:
        window.close()


def test_background_profile_reuses_prepared_planes_after_area_changes_and_reopening(source: Path,
                                                                                   monkeypatch: pytest.MonkeyPatch,
                                                                                   ) -> None:
    """
    Reuse the current preview and prepared stack without decoding or subtracting again.
    """
    window = BackgroundTunerWindow(source.parent, settings=BGSubSettings(size=3))
    window.show()
    QApplication.processEvents()
    calls: list[tuple[int, str, int]] = []
    compute = BackgroundTuningSession.compute_plane

    def record_compute(self: BackgroundTuningSession, image: Any, settings: BGSubSettings,
                       frame: int, channel: str, z: int) -> Any:
        """
        Count processing calls across preview and independent profile workers.
        """
        calls.append((frame, channel, z))
        return compute(self, image, settings, frame, channel, z)

    monkeypatch.setattr(BackgroundTuningSession, "compute_plane", record_compute)
    try:
        measurement = window.measurement
        measurement.drawing.set_rectangle((3, 3, 18, 18))
        window.run_button.click()
        _wait(lambda: window._thread is None)
        measurement.profile_button.click()
        dialog = measurement.dialog
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive() and len(dialog.plot.listDataItems()) == 2)
        assert len(calls) == window.frame_slider.maximum() + 1
        assert sum(frame == 0 for frame, _, _ in calls) == 1
        before = dialog.plot.listDataItems()[0].getData()[1].copy()

        def forbid_recompute(*args: Any, **kwargs: Any) -> Any:
            """
            Fail if moving or reopening repeats image loading or background subtraction.
            """
            pytest.fail("Prepared profiles must reuse existing image planes")

        monkeypatch.setattr(FischImageSession, "display_frame", forbid_recompute)
        monkeypatch.setattr(BackgroundTuningSession, "compute_plane", forbid_recompute)
        measurement.drawing.set_rectangle((10, 3, 23, 18))
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive())
        assert not np.array_equal(dialog.plot.listDataItems()[0].getData()[1], before)
        assert "preparing" not in dialog.status.text()
        view = dialog.plot.getViewBox()
        view.setRange(xRange=(500, 501), yRange=(-1000000, -900000), padding=0)
        assert not any(view.autoRangeEnabled())
        dialog.close()
        QApplication.processEvents()
        measurement.profile_button.click()
        _wait(lambda: dialog._thread is None and not dialog._timer.isActive())
        assert dialog.isVisible()
        assert dialog._request is not None
        assert len(dialog.plot.listDataItems()) == 2
        assert all(view.autoRangeEnabled())
        assert view.viewRange()[0][0] <= 1 and view.viewRange()[0][1] >= 3
        assert view.viewRange()[1][0] > -900000
        directory = dialog._cache._directory
        assert directory is not None
        cache_path = Path(directory.name)
        assert cache_path.is_dir()
        window.close()
        assert not cache_path.exists()
    finally:
        window.close()
