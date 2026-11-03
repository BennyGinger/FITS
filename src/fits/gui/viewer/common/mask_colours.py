"""A reusable palette/preset/custom display-colour control."""

from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QComboBox, QWidget


class MaskColourControl(QComboBox):
    """
    Choose label colours without modifying mask values or processing settings.
    """

    colour_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Offer a label palette, common solid colours, and the standard colour dialog.
        """
        super().__init__(parent)
        self._custom = QColor("yellow")
        self.addItem("Palette", None)
        for name in ("White", "Yellow", "Red", "Green", "Cyan", "Blue", "Magenta"):
            self.addItem(name, name.lower())
        self.addItem("Custom…", "custom")
        self.currentIndexChanged.connect(self._selected)

    def colour(self) -> QColor | None:
        """
        Return None for the label palette or the selected solid colour.
        """
        value = self.currentData()
        return self._custom if value == "custom" else QColor(value) if value else None

    def _selected(self, index: int) -> None:
        """
        Resolve the custom dialog only when the user selects its menu entry.
        """
        if self.itemData(index) == "custom":
            selected = QColorDialog.getColor(self._custom, self, "Mask colour")
            if selected.isValid():
                self._custom = selected
        self.colour_changed.emit(self.colour())

    def selection(self) -> tuple[int, QColor]:
        """
        Return the menu and custom colour state for one viewer tab.
        """
        return self.currentIndex(), QColor(self._custom)

    def set_selection(self, selection: tuple[int, QColor]) -> None:
        """
        Restore a tab selection without reopening the custom colour dialog.
        """
        index, colour = selection
        with QSignalBlocker(self):
            self._custom = QColor(colour)
            self.setCurrentIndex(index)
        self.colour_changed.emit(self.colour())
