"""Selection clicks and panning drags must remain distinct in both viewer modes."""
from typing import cast

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from fits.gui.viewer.tracking.window import TrackingViewerWindow

_APP: QApplication | None = None


@pytest.mark.parametrize("editing", [False, True])
def test_ctrl_left_click_selects_but_drag_only_pans(monkeypatch, editing):
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    window = TrackingViewerWindow(editing_enabled=editing, selection_enabled=True)
    selected = []
    monkeypatch.setattr(window, "_tracking_session", object())
    monkeypatch.setattr(window, "_track_at_position", lambda *args: 7)
    monkeypatch.setattr(window, "_select_single_track", selected.append)
    monkeypatch.setattr(window, "_toggle_track_selection", selected.append)
    window.image_viewer.set_image(np.zeros((100, 100)))
    window.show()
    _APP.processEvents()
    viewport = cast(QWidget, window.image_viewer.canvas.viewport())
    scene_center = window.image_viewer.view_box.sceneBoundingRect().center()
    point = cast(QPoint, window.image_viewer.canvas.mapFromScene(scene_center))
    control = Qt.KeyboardModifier.ControlModifier
    try:
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point)
        assert selected == []
        QTest.mouseClick(viewport, Qt.MouseButton.RightButton, control, point)
        assert selected == []
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, control, point)
        assert selected == [7]
        before = window.image_viewer.view_box.viewRange()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, control, point)
        target = point + QPoint(50, 20)
        # Supply held-button/modifier state explicitly; QTest.mouseMove does not
        # reliably retain Ctrl in the offscreen platform.
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(target),
                           QPointF(viewport.mapToGlobal(target)), Qt.MouseButton.NoButton,
                           Qt.MouseButton.LeftButton, control)
        _APP.sendEvent(viewport, move)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, control, point + QPoint(50, 20))
        assert selected == [7]
        assert window.image_viewer.view_box.viewRange() != before
    finally:
        # The fake session deliberately has no resources or close method.
        monkeypatch.setattr(window, "_tracking_session", None)
        window.close()
