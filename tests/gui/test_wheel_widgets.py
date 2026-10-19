"""Protect parameter values while scrolling settings, with keyboard focus support."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QVBoxLayout, QWidget

from fits.gui.settings.wheel_widgets import FocusWheelComboBox, FocusWheelDoubleSpinBox
from fits.gui.settings.wheel_widgets import FocusWheelSlider, FocusWheelSpinBox

_APP = None


def send_wheel(widget):
    """Deliver the same wheel gesture directly to a parameter control."""
    event = QWheelEvent(
        QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))),
        QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize("widget_class", [
    FocusWheelSpinBox, FocusWheelDoubleSpinBox, FocusWheelComboBox, FocusWheelSlider])
def test_wheel_requires_current_focus_and_otherwise_scrolls_panel(widget_class):
    """Unfocused editors scroll their panel; Tab focus allows value adjustment."""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    contents = QWidget()
    layout = QVBoxLayout(contents)
    other = QPushButton("Other control")
    layout.addWidget(other)
    editor = widget_class()
    if isinstance(editor, FocusWheelComboBox):
        editor.addItems([str(index) for index in range(30)])
        editor.setCurrentIndex(15)
        value = editor.currentIndex
    else:
        editor.setRange(0, 30)
        editor.setValue(15)
        value = editor.value
    layout.addWidget(editor)
    contents.setMinimumHeight(1000)
    scroll.setWidget(contents)
    scroll.resize(300, 200)
    scroll.show()
    scroll.activateWindow()
    try:
        other.setFocus()
        QTest.qWait(10)
        before = value()
        send_wheel(editor)
        assert value() == before
        assert not editor.hasFocus()
        assert scroll.verticalScrollBar().value() > 0

        editor.setFocus(Qt.FocusReason.TabFocusReason)
        assert editor.hasFocus()
        send_wheel(editor)
        assert value() != before

        other.setFocus()
        before = value()
        send_wheel(editor)
        assert value() == before
    finally:
        scroll.close()
