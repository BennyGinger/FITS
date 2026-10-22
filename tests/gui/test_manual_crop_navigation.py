"""Shared manual rectangles must leave Ctrl+drag available for image panning."""

import os
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from fits.gui.viewer.common.crop import CropPanel
from fits.gui.viewer.common.image_viewer import FitsImageViewer

_APP = None


@pytest.mark.parametrize("bounds", [None, (20, 20, 80, 80)])
def test_ctrl_drag_pans_without_drawing_or_changing_manual_rectangle(bounds):
    """Pan through the real viewport with an enabled, empty or existing rectangle."""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    window = QWidget()
    layout = QVBoxLayout(window)
    viewer = FitsImageViewer()
    panel = CropPanel(automatic=False)
    panel.bind(viewer)
    layout.addWidget(viewer)
    layout.addWidget(panel)
    window.resize(800, 800)
    window.show()
    try:
        viewer.set_image(np.ones((100, 100), dtype=np.uint16))
        panel.reset((100, 100))
        panel.enabled.setChecked(True)
        if bounds is not None:
            panel.set_bounds(bounds)
        QTest.qWait(20)
        previous = viewer.view_box.viewRange()
        viewport = cast(QWidget, viewer.canvas.viewport())
        start = cast(QPoint, viewer.canvas.mapFromScene(viewer.view_box.mapViewToScene(QPointF(40, 40))))
        end = start + QPoint(60, 30)
        control = Qt.KeyboardModifier.ControlModifier
        QTest.mouseMove(viewport, start)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, control, start)
        for position in (start + QPoint(30, 15), end):
            move = QMouseEvent(QEvent.Type.MouseMove, QPointF(position),
                               QPointF(viewport.mapToGlobal(position)), Qt.MouseButton.NoButton,
                               Qt.MouseButton.LeftButton, control)
            QApplication.sendEvent(viewport, move)
            QTest.qWait(20)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, control, end)
        QApplication.processEvents()
        assert viewer.view_box.viewRange() != previous
        assert panel.bounds == bounds
        assert panel.enabled.isChecked()
        assert panel._gesture == ""
    finally:
        window.close()
