from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)


class ValueWidget(QWidget):
    """Common interface for widgets that edit one TOML value."""

    value_changed = Signal(object)

    def value(self) -> Any:
        raise NotImplementedError


class BoolWidget(QCheckBox):
    value_changed = Signal(object)

    def __init__(self, value: bool) -> None:
        super().__init__()
        self.setChecked(value)
        self.toggled.connect(self.value_changed.emit)

    def value(self) -> bool:
        return self.isChecked()


class IntWidget(QSpinBox):
    value_changed = Signal(object)

    def __init__(self, value: int) -> None:
        super().__init__()
        self.setRange(-1_000_000_000, 1_000_000_000)
        self.setValue(value)
        self.valueChanged.connect(self.value_changed.emit)

    def value(self) -> int:
        return super().value()


class FloatWidget(QDoubleSpinBox):
    value_changed = Signal(object)

    def __init__(self, value: float) -> None:
        super().__init__()
        self.setDecimals(6)
        self.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.setValue(value)
        self.valueChanged.connect(self.value_changed.emit)

    def value(self) -> float:
        return super().value()


class TextWidget(QLineEdit):
    value_changed = Signal(object)

    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.editingFinished.connect(lambda: self.value_changed.emit(self.value()))

    def value(self) -> str:
        return self.text().strip()


class ListWidget(QLineEdit):
    value_changed = Signal(object)

    def __init__(self, value: list[Any]) -> None:
        super().__init__(", ".join(str(item) for item in value))
        self.setPlaceholderText("Comma-separated values")
        self.editingFinished.connect(lambda: self.value_changed.emit(self.value()))

    def value(self) -> list[str]:
        return [part.strip() for part in self.text().split(",") if part.strip()]


class ChoiceWidget(QComboBox):
    value_changed = Signal(object)

    def __init__(self, value: str, choices: tuple[str, ...]) -> None:
        super().__init__()
        values = list(choices)
        if value not in values:
            values.insert(0, value)
        self.addItems(values)
        self.setCurrentText(value)
        self.currentTextChanged.connect(self.value_changed.emit)

    def value(self) -> str:
        return self.currentText()


def create_field_widget(value: Any, choices: tuple[str, ...] | None = None) -> ValueWidget:
    if choices is not None and isinstance(value, str):
        return ChoiceWidget(value, choices)  # type: ignore[return-value]
    if isinstance(value, bool):
        return BoolWidget(value)  # type: ignore[return-value]
    if isinstance(value, int):
        return IntWidget(value)  # type: ignore[return-value]
    if isinstance(value, float):
        return FloatWidget(value)  # type: ignore[return-value]
    if isinstance(value, list):
        return ListWidget(value)  # type: ignore[return-value]
    return TextWidget(str(value))  # type: ignore[return-value]
