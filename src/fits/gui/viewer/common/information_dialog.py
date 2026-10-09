"""Shared searchable help table for image viewers."""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

HelpRow = tuple[str, str, str, str]

COMMON_HELP: tuple[HelpRow, ...] = (
    ("S", "Save / apply current work", "REF / ROI / SegTune / RegTune / Tracking",
     "Current mask, settings, or ready editing preview"),
    ("Ctrl+Z", "Undo the latest edit or preview", "REF / ROI / Tracking", "Editing"),
    ("X", "Toggle mask overlay", "All viewers", "All modes"),
    ("← / → or A / D", "Previous / next frame", "All viewers", "All modes"),
    ("↑ / ↓ or W / Z", "Next / previous Z plane", "All viewers", "All modes"),
    ("C", "Next image channel", "All viewers", "All modes"),
    ("Ctrl+left click (hold), drag", "Pan image", "All viewers", "All modes"),
    ("Ctrl+scroll", "Zoom image",
     "All viewers", "All modes"),
)

EDITING_HELP: tuple[HelpRow, ...] = (
    ("Ctrl+D", "Remove the current mask", "REF / ROI / Tracking",
     "Editing; current plane (REF/ROI) or selected track's current mask (Tracking)"),
    ("Ctrl+Shift+D", "Remove all masks in the selection", "REF / ROI / Tracking",
     "Editing; selected channel (REF/ROI) or selected track (Tracking), across frames"),
    ("Left click / drag", "Draw / add", "REF / ROI / Tracking",
     "Editing; REF/ROI: Replace/Edit; Tracking: Add/Edit or Split Mask"),
    ("Right click / drag", "Erase / remove", "REF / ROI / Tracking",
     "Editing; REF/ROI: Replace/Edit; Tracking: Add/Edit"),
)

MASK_HELP: tuple[HelpRow, ...] = (
    ("Shift+left click (hold), drag", "Select and move the connected mask region under the cursor",
     "REF / ROI", "Drawing"),
)

SEGMENTATION_HELP: tuple[HelpRow, ...] = (
    ("R", "Run preview", "SegTune / RegTune", "Tuning; RegTune can cancel an active preview"),
)

REGISTRATION_HELP = SEGMENTATION_HELP

TRACKING_HELP: tuple[HelpRow, ...] = (
    ("Ctrl+left click mask or centroid", "Select / unselect track", "Tracking", "Edit or selection enabled"),
)

# Mode details preserve the differences behind the shared gestures. Full-catalog
# inspection uses the general conditions above; normal dialogs show local ones.
HELP_CONDITIONS: dict[str, dict[str, str]] = {
    "REF / ROI": {
        "S": "Current mask",
        "Ctrl+Z": "Current plane",
        "Ctrl+D": "Current plane; session only",
        "Ctrl+Shift+D": "Selected channel; all frames and Z planes; session only",
        "Left click / drag": "Replace / Edit; selected drawing tool",
        "Right click / drag": "Replace / Edit; selected drawing tool",
    },
    "SegTune": {"S": "Current settings", "R": "Tuning"},
    "RegTune": {"S": "Current tab; requires a matching ready preview",
                "X": "Switch original / registered image"},
    "Tracking": {
        "S": "Split / Add/Edit; ready preview (applies in session)",
        "Ctrl+D": "Edit; selected track's mask in the current frame",
        "Ctrl+Shift+D": "Edit; selected track; all frames in the current channel/Z plane",
        "Left click / drag": (
            "Edit → Add/Edit: click predicts/adds, drag brushes.\n"
            "Edit → Split Mask: click/drag marks the division inside the selected mask."),
        "Right click / drag": "Edit → Add/Edit: click predicts/removes, drag erases",
    },
}

# One catalog serves every viewer; GUI applicability is internal filter metadata.
VIEWER_HELP = (*COMMON_HELP, *EDITING_HELP, *MASK_HELP, *SEGMENTATION_HELP, *TRACKING_HELP)


class ViewerInformationDialog(QDialog):
    """Keep viewer controls and their descriptions readable and easy to find."""

    def __init__(self, parent: QWidget | None = None, *, title: str, version: str,
                 gui: str | None = None, rows: Sequence[HelpRow] = VIEWER_HELP,
                 editing_enabled: bool = True, selection_enabled: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {title}")
        self.resize(980, 620)
        if gui is not None:
            active_guis = set(gui.split(" / "))
            rows = [row for row in rows
                    if row[2] == "All viewers" or active_guis.intersection(row[2].split(" / "))]
        if gui == "Tracking":
            rows = [row for row in rows
                    if (editing_enabled or (not row[3].startswith("Edit")
                                            and row[0] not in {"S", "Ctrl+Z"}))
                    or (row[0] == "Ctrl+left click mask or centroid" and selection_enabled)]
        conditions = HELP_CONDITIONS.get(gui or "", {})
        rows = [(shortcut, function, scope, conditions.get(shortcut, mode))
                for shortcut, function, scope, mode in rows]
        if gui == "RegTune":
            rows = [(shortcut, "Toggle original / registered image" if shortcut == "X" else function,
                     scope, mode) for shortcut, function, scope, mode in rows]
        layout = QVBoxLayout(self)
        intro = QLabel("Viewer controls and keyboard shortcuts")
        intro.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(intro)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a shortcut, function, or mode…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.table = QTableWidget(len(rows), 4)
        self.table.setHorizontalHeaderLabels(["Shortcut", "Function", "GUI", "Mode / condition"])
        self.table.setColumnHidden(2, gui is not None)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        for index, row in enumerate(rows):
            for column, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(index, column, item)
        layout.addWidget(self.table, 1)
        self.search.textChanged.connect(self._filter)
        footer = QLabel(f"FITS {version}")
        layout.addWidget(footer)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.setFocus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_to_screen()

    def _fit_to_screen(self) -> None:
        """Fit wrapped columns and all rows within the current screen's work area."""
        available = self.screen().availableGeometry()
        width = min(1200, available.width() - 40)
        self.resize(width, min(620, available.height() - 60))
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        table_width = self.table.viewport().width()
        metrics = self.table.fontMetrics()
        shortcut_width = max(
            (metrics.horizontalAdvance(row[0]) + 28 for row in VIEWER_HELP), default=240)
        self.table.setColumnWidth(0, min(shortcut_width, int(table_width * 0.35)))
        if not self.table.isColumnHidden(2):
            self.table.setColumnWidth(2, min(200, int(table_width * 0.20)))
        remaining = table_width - self.table.columnWidth(0)
        if not self.table.isColumnHidden(2):
            remaining -= self.table.columnWidth(2)
        self.table.setColumnWidth(3, int(remaining * 0.53))
        self.table.resizeRowsToContents()
        table_height = sum(self.table.rowHeight(row) for row in range(self.table.rowCount()))
        table_height += self.table.horizontalHeader().height() + 4
        other_height = layout.contentsMargins().top() + layout.contentsMargins().bottom()
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is not None and item.widget() is not self.table:
                other_height += item.sizeHint().height()
        other_height += layout.spacing() * (layout.count() - 1)
        self.resize(width, min(table_height + other_height + 8, available.height() - 60))
        self.move(available.center() - self.rect().center())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.table.resizeRowsToContents()

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        for row in range(self.table.rowCount()):
            values = []
            for column in (0, 1, 3):
                item = self.table.item(row, column)
                if item is not None:
                    values.append(item.text())
            self.table.setRowHidden(row, query not in " ".join(values).casefold())

