from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPaintEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QLineEdit,
    QWidget,
)
from fits.gui.settings.wheel_widgets import (
    FocusWheelComboBox, FocusWheelDoubleSpinBox, FocusWheelSpinBox,
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


class IntWidget(FocusWheelSpinBox):
    value_changed = Signal(object)

    def __init__(self, value: int) -> None:
        super().__init__()
        self.setRange(-1_000_000_000, 1_000_000_000)
        self.setValue(value)
        self.valueChanged.connect(self.value_changed.emit)

    def value(self) -> int:
        return super().value()


class FloatWidget(FocusWheelDoubleSpinBox):
    value_changed = Signal(object)

    def __init__(self, value: float) -> None:
        super().__init__()
        self.setDecimals(6)
        self.setRange(-1_000_000_000.0, 1_000_000_000.0)
        if value < 1:
            self.setSingleStep(0.1)
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


class ChannelSelectionWidget(FocusWheelComboBox):
    """Collapsed channel summary with a persistent popup of checked choices."""

    value_changed = Signal(object)

    def __init__(self, channels: list[str], selected: list[str], *, allow_none: bool = False) -> None:
        """
        Offer multiple checked channels and an optional exclusive None entry.
        """
        super().__init__()
        self._allow_none = allow_none
        self._help_tooltip = ""
        self._summary = ""
        self._updating_choices = False
        self._pressed_popup_row: int | None = None
        self._items = QStandardItemModel(self)
        self.setModel(self._items)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(12)
        self.setMaxVisibleItems(12)
        self.view().viewport().installEventFilter(self)
        self.view().installEventFilter(self)
        self._items.itemChanged.connect(self._selection_changed)
        self.set_channels(channels, selected)

    def set_channels(self, channels: list[str], selected: list[str] | None = None) -> None:
        """
        Refresh choices silently, preserving an open popup when nothing changed.
        """
        selected_values = set(self.value() if selected is None else selected).intersection(channels)
        options: list[str | None] = ([None] if self._allow_none else []) + list(channels)
        checked: set[str | None] = set(selected_values)
        if self._allow_none and not checked:
            checked.add(None)
        current = [self.itemData(index) for index in range(self.count())]
        current_checked = {self.itemData(index) for index in range(self.count())
                           if self.is_channel_selected(index)}
        if current == options and current_checked == checked:
            self._update_summary()
            return
        self._updating_choices = True
        with QSignalBlocker(self):
            self._items.clear()
            for channel in options:
                item = QStandardItem("None" if channel is None else channel)
                item.setData(channel, Qt.ItemDataRole.UserRole)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if channel in checked else Qt.CheckState.Unchecked)
                self._items.appendRow(item)
        self._updating_choices = False
        self._update_summary()

    def set_channel_selected(self, index: int, selected: bool) -> None:
        """
        Check or uncheck one channel using the same rules as a popup click.
        """
        item = self._items.item(index)
        if item is not None:
            item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def is_channel_selected(self, index: int) -> bool:
        """
        Report whether a popup entry is checked.
        """
        item = self._items.item(index)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def clearSelection(self) -> None:
        """
        Clear all channel checks, restoring None for optional exclusions.
        """
        with QSignalBlocker(self._items):
            for index in range(self.count()):
                item = self._items.item(index)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Checked if self._allow_none and index == 0
                                       else Qt.CheckState.Unchecked)
        self._update_summary()
        self.value_changed.emit(self.value())

    def _selection_changed(self, changed: QStandardItem) -> None:
        """
        Keep None exclusive and publish the updated channel selection.
        """
        if self._updating_choices:
            return
        if self._allow_none:
            with QSignalBlocker(self._items):
                if changed.data(Qt.ItemDataRole.UserRole) is None and changed.checkState() == Qt.CheckState.Checked:
                    for index in range(1, self.count()):
                        self.set_channel_selected(index, False)
                else:
                    self.set_channel_selected(0, not bool(self.value()))
        self._update_summary()
        self.value_changed.emit(self.value())

    def value(self) -> list[str]:
        """
        Return checked channel labels in source order, excluding None.
        """
        return [self.itemText(index) for index in range(self.count())
                if self.itemData(index) is not None and self.is_channel_selected(index)]

    def selection_text(self) -> str:
        """
        Return the complete, unabridged selection shown by the collapsed control.
        """
        return self._summary

    def showPopup(self) -> None:
        """
        Open for inspection without carrying a mouse press into the popup.
        """
        self._pressed_popup_row = None
        super().showPopup()

    def setToolTip(self, tooltip: str) -> None:
        """
        Retain parameter help alongside the complete selected-channel list.
        """
        self._help_tooltip = tooltip
        self._update_summary()

    def _update_summary(self) -> None:
        """
        Refresh the display, accessible description and full-selection tooltip.
        """
        selected = self.value()
        self._summary = ", ".join(selected) if selected else (
            "None" if self._allow_none else "Select channels…" if self.count() else "No channels available")
        super().setToolTip(self._summary + ("\n\n" + self._help_tooltip if self._help_tooltip else ""))
        self.setAccessibleDescription(self._summary)
        self.update()
        self.view().viewport().update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """
        Paint the selected names on one line with an ellipsis when they do not fit.
        """
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        rectangle = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                                 QStyle.SubControl.SC_ComboBoxEditField, self)
        option.currentText = self.fontMetrics().elidedText(self._summary, Qt.TextElideMode.ElideRight,
                                                          max(0, rectangle.width()))
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """
        Toggle popup checks without closing it; let native outside clicks dismiss it.
        """
        if watched is self.view().viewport() and isinstance(event, QMouseEvent):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                index = self.view().indexAt(event.position().toPoint())
                self._pressed_popup_row = index.row() if index.isValid() else None
                if index.isValid():
                    self.view().setCurrentIndex(index)
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                index = self.view().indexAt(event.position().toPoint())
                pressed_row = self._pressed_popup_row
                self._pressed_popup_row = None
                if index.isValid():
                    if pressed_row == index.row():
                        self.set_channel_selected(index.row(), not self.is_channel_selected(index.row()))
                    return True
        if watched in (self.view(), self.view().viewport()) and isinstance(event, QKeyEvent):
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space:
                index = self.view().currentIndex()
                if index.isValid():
                    self.set_channel_selected(index.row(), not self.is_channel_selected(index.row()))
                return True
        return super().eventFilter(watched, event)


class ExportChannelsWidget(ChannelSelectionWidget):
    """Select exported channels from the source-channel labels."""

    def __init__(self, value: str | list[str], channels: list[str]) -> None:
        """
        Select every source channel by default while retaining saved subsets.
        """
        selected = channels if value == "all" else ([value] if isinstance(value, str) else value)
        super().__init__(channels, selected)


class ChannelChoiceWidget(FocusWheelComboBox):
    """Choose one available image channel, optionally leaving it unspecified."""

    value_changed = Signal(object)

    def __init__(self, channels: list[str], value: Any, *, optional: bool) -> None:
        """
        Start with None for optional choices and a blank entry for required ones.
        """
        super().__init__()
        self._optional = optional
        self.set_channels(channels, value)
        self.currentIndexChanged.connect(lambda: self.value_changed.emit(self.value()))

    def set_channels(self, channels: list[str], value: Any) -> None:
        """
        Keep a valid saved label or index without introducing unavailable choices.
        """
        if isinstance(value, int):
            value = channels[value] if 0 <= value < len(channels) else None
        with QSignalBlocker(self):
            self.clear()
            self.addItem("None" if self._optional else "", "None" if self._optional else "")
            for channel in channels:
                self.addItem(channel, channel)
            self.setCurrentIndex(max(0, self.findData(value)))

    def value(self) -> str:
        """
        Return the selected label or the appropriate unspecified value.
        """
        return str(self.currentData())


class ChoiceWidget(FocusWheelComboBox):
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
