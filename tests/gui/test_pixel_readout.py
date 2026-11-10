"""Hover values follow image planes rather than their clipped or blended display."""

import os
from collections.abc import Iterator
from typing import Any, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.common.image_viewer import FitsImageViewer
from fits.gui.viewer.masks import MaskDrawingWindow


_APP: QApplication | None = None


@pytest.fixture
def viewer(monkeypatch: pytest.MonkeyPatch) -> Iterator[FitsImageViewer]:
    """
    Open the shared canvas and deliver hover events without relying on a desktop pointer.
    """
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    window = FitsImageViewer()
    window.resize(600, 400)
    window.show()
    QApplication.processEvents()
    monkeypatch.setattr(window.pixel_readout._viewport, "underMouse", lambda: True)
    yield window
    window.close()
    window.deleteLater()
    QApplication.processEvents()


def _hover(viewer: FitsImageViewer, x: float, y: float) -> None:
    """
    Send a scene mouse event through the throttled hover connection.
    """
    point = viewer.image_item.mapToScene(cast(Any, QPointF(x, y)))
    cast(Any, viewer.canvas.scene()).sigMouseMoved.emit(point)
    QTest.qWait(80)


def test_single_hover_uses_unclipped_values_and_updates_with_stationary_mouse(viewer: FitsImageViewer) -> None:
    """
    Keep scientific intensities independent of display clipping, LUTs and masks.
    """
    pixels = np.array([[12.34, -23.45], [65535, 3]], dtype=np.float32)
    viewer.set_image(pixels)
    QApplication.processEvents()
    _hover(viewer, 1.2, 0.2)
    readout = viewer.pixel_readout
    assert readout.single_value.text() == "-23.5"
    assert all(tag.text() == "" for tag in readout.tags)
    assert np.asarray(viewer.image_item.image)[0, 1] == 0
    assert pixels[0, 1] < 0
    viewer.set_image(np.full((2, 2), 87, dtype=np.uint16))
    assert readout.single_value.text() == "87"
    viewer.set_display_levels((0, 1))
    _hover(viewer, 0.2, 1.2)
    assert readout.single_value.text() == "87"
    _hover(viewer, -0.1, 0.2)
    assert readout.single_value.text() == "—"


def test_composite_hover_samples_both_planes_and_elides_only_names(viewer: FitsImageViewer) -> None:
    """
    Show two numeric columns with bounded tags and complete labels in tooltips.
    """
    viewer.set_image(np.ones((2, 2), dtype=np.uint16))
    first = np.full((2, 2), 302, dtype=np.uint16)
    second = np.full((2, 2), 56.625, dtype=np.float32)
    readout = viewer.pixel_readout
    readout.set_planes((("GFP_with_a_very_long_channel_name", first), ("RFP", second)))
    width = readout.width()
    QApplication.processEvents()
    _hover(viewer, 0.2, 0.2)
    assert [label.text() for label in readout.values] == ["302", "56.6"]
    assert readout.tags[0].text().endswith("…")
    assert readout.tags[1].text() == "RFP"
    assert readout.tags[0].toolTip() == "GFP_with_a_very_long_channel_name"
    assert readout.values[1].toolTip() == "RFP: 56.625"
    assert readout.values[1].toolTip() == "RFP: 56.625"
    assert readout.width() == width
    readout.set_planes(())
    assert readout.single_value.text() == "—"


def test_shared_lut_layout_places_compact_buttons_above_graph_and_readout_at_bottom(viewer: FitsImageViewer) -> None:
    """
    Align the compact range controls above the graph and values with its bottom.
    """
    window: ImageToolWindow = MaskDrawingWindow()
    try:
        readout = window.image_viewer.pixel_readout
        window.resize(1700, 1000)
        window.show()
        QApplication.processEvents()
        assert window.auto_scale_button.width() == window.full_range_button.width() == readout.width()
        histogram = cast(QWidget, window.image_viewer.histogram)
        auto = window.auto_scale_button.mapTo(window.lut_controls, window.auto_scale_button.rect().topLeft())
        full = window.full_range_button.mapTo(window.lut_controls, window.full_range_button.rect().topLeft())
        graph = histogram.mapTo(window.lut_controls, histogram.rect().topLeft())
        assert full.x() < auto.x()
        assert full.y() == auto.y()
        assert auto.y() + window.auto_scale_button.height() <= graph.y()
        graph_bottom = histogram.mapTo(window.lut_controls, histogram.rect().bottomLeft()).y()
        readout_bottom = readout.mapTo(window.lut_controls, readout.rect().bottomLeft()).y()
        assert abs(graph_bottom - readout_bottom) <= 1
        footer = window.viewer_actions.parentWidget()
        assert footer is not None
        layout = footer.layout()
        assert isinstance(layout, QHBoxLayout)
        assert layout.indexOf(window.lut_controls) < layout.indexOf(window.viewer_actions)
    finally:
        window.close()
