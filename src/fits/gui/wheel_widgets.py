from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QAbstractScrollArea, QComboBox, QDoubleSpinBox, QSlider, QSpinBox,
)


class _FocusWheelMixin:
    """Let a parent scroll area handle the wheel until this editor has focus."""

    _wheel_armed = False

    def mousePressEvent(self, event: Any) -> None:
        self._wheel_armed = True
        super().mousePressEvent(event)

    def focusOutEvent(self, event: Any) -> None:
        self._wheel_armed = False
        super().focusOutEvent(event)

    def wheelEvent(self, event: Any) -> None:
        if not self._wheel_armed:
            parent = self.parentWidget()
            while parent is not None and not isinstance(parent, QAbstractScrollArea):
                parent = parent.parentWidget()
            if isinstance(parent, QAbstractScrollArea):
                bar = parent.verticalScrollBar()
                delta = event.pixelDelta().y() or event.angleDelta().y()
                bar.setValue(bar.value() - delta)
                event.accept()
            else:
                event.ignore()
            return
        super().wheelEvent(event)


class FocusWheelSpinBox(_FocusWheelMixin, QSpinBox):
    pass


class FocusWheelDoubleSpinBox(_FocusWheelMixin, QDoubleSpinBox):
    pass


class FocusWheelComboBox(_FocusWheelMixin, QComboBox):
    pass


class FocusWheelSlider(_FocusWheelMixin, QSlider):
    pass
