from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractScrollArea, QComboBox, QDoubleSpinBox, QSlider, QSpinBox, QWidget

# Give the type checker a QWidget base without adding it at runtime (avoids MRO conflicts).
_MixinBase = QWidget if TYPE_CHECKING else object


class _FocusWheelMixin(_MixinBase):
    """Let a parent scroll area handle the wheel until this editor has focus."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Allow click and keyboard focus without letting the wheel acquire focus."""
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: Any) -> None:
        """Change a focused value or scroll the containing settings panel."""
        if not self.hasFocus():
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
    """Require focus before mouse-wheel changes to the value."""


class FocusWheelDoubleSpinBox(_FocusWheelMixin, QDoubleSpinBox):
    """Require focus before mouse-wheel changes to the value."""


class FocusWheelComboBox(_FocusWheelMixin, QComboBox):
    """Require focus before mouse-wheel changes to the value."""


class FocusWheelSlider(_FocusWheelMixin, QSlider):
    """Require focus before mouse-wheel changes to the value."""
