"""Conversion channel labels alongside detected ND2 display colors."""

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import QHeaderView, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from scope_io.metadata.channel_colors import channel_color_name, conversion_channel_labels
from fisch.gui.settings.field_widgets import ValueWidget


def _color_icon(color: str) -> QIcon:
    """
    Draw a colored ball with an outline that remains visible for white channels.
    """
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#888888"))
    painter.setBrush(QColor(color))
    painter.drawEllipse(3, 3, 12, 12)
    painter.end()
    return QIcon(pixmap)


def _advances_label(event: QEvent) -> bool:
    """Recognize unmodified Tab and both Enter keys."""
    return (event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier))


class _LabelDelegate(QStyledItemDelegate):
    """Commit label edits before navigating past the read-only columns."""

    def __init__(self, table: "_ChannelLabelsTable") -> None:
        super().__init__(table)
        self._table = table

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Finish editing on Tab or Enter and open the next blank label."""
        if isinstance(watched, QWidget) and _advances_label(event):
            row = self._table.currentRow()
            self.commitData.emit(watched)
            self.closeEditor.emit(watched, QStyledItemDelegate.EndEditHint.NoHint)
            self._table.edit_next_empty_label(row)
            return True
        return super().eventFilter(watched, event)


class _ChannelLabelsTable(QTableWidget):
    """Navigate directly between empty channel names during label entry."""

    def __init__(self) -> None:
        super().__init__(0, 3)
        self.setItemDelegateForColumn(2, _LabelDelegate(self))

    def edit_next_empty_label(self, row: int) -> None:
        """Search following rows, wrapping once and skipping the current row."""
        count = self.rowCount()
        for offset in range(1, count):
            item = self.item((row + offset) % count, 2)
            if item is not None and not item.text().strip():
                self.setCurrentItem(item)
                self.editItem(item)
                return

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Keep navigation in the label column when an editor is closed."""
        if self.currentColumn() == 2 and _advances_label(event):
            self.edit_next_empty_label(self.currentRow())
            event.accept()
            return
        super().keyPressEvent(event)


class ConversionChannelsWidget(ValueWidget):
    """Keep editable labels separate from read-only source colors and fallback names."""

    def __init__(self, labels: list[str]) -> None:
        """
        Build the channel-number, expected-color and label table.
        """
        super().__init__()
        self._labels = labels
        self._count: int | None = None
        self._colors: list[str | None] | None = None
        self.table = _ChannelLabelsTable()
        self.table.setHorizontalHeaderLabels(["Channel", "Expected color", "Label"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        self.table.cellChanged.connect(self._label_changed)
        self._rebuild()

    def value(self) -> list[str]:
        """
        Return user labels only, preserving blanks and mismatched saved counts.
        """
        return list(self._labels)

    def set_labels(self, labels: list[str]) -> None:
        """
        Replace a saved draft without emitting an edit signal.
        """
        self._labels = list(labels)
        self._rebuild()

    def set_source(self, count: int | None, colors: list[str | None] | None) -> None:
        """
        Refresh detected metadata without writing defaults into the user's label cells.
        """
        if (count, colors) == (self._count, self._colors):
            return
        self._count, self._colors = count, colors
        self._rebuild()

    def _rebuild(self) -> None:
        """
        Size rows from detected channels, retaining any surplus saved labels for correction.
        """
        rows = max(self._count or 0, len(self._labels))
        colors = self._colors if not self._labels or len(self._labels) == self._count else None
        defaults = conversion_channel_labels(self._labels, rows, colors)
        with QSignalBlocker(self.table):
            self.table.setRowCount(rows)
            for index in range(rows):
                number = QTableWidgetItem(str(index + 1))
                number.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(index, 0, number)
                color = colors[index] if colors is not None and index < len(colors) else None
                detected = QTableWidgetItem(channel_color_name(color) or "nan")
                detected.setFlags(number.flags())
                if color is not None:
                    detected.setIcon(_color_icon(color))
                    detected.setToolTip(color)
                self.table.setItem(index, 1, detected)
                label = QTableWidgetItem(self._labels[index] if index < len(self._labels) else "")
                label.setToolTip(f"Leave blank to use {defaults[index]}.")
                self.table.setItem(index, 2, label)
        height = self.table.horizontalHeader().height() + min(rows, 6) * self.table.verticalHeader().defaultSectionSize() + 4
        self.table.setFixedHeight(max(height, 75))

    def _label_changed(self, row: int, column: int) -> None:
        """
        Publish positional labels after a user edits a label cell.
        """
        if column != 2:
            return
        labels = [item.text().strip() if (item := self.table.item(index, 2)) is not None else ""
                  for index in range(self.table.rowCount())]
        if self._count is not None:
            while len(labels) > self._count and not labels[-1]:
                labels.pop()
        self._labels = labels if any(labels) else []
        self._rebuild()
        self.value_changed.emit(self.value())
