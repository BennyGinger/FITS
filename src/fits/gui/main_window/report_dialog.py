"""Readable GUI presentation of the existing plain-text pipeline reports."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QPlainTextEdit, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget


_COUNTS = re.compile(
    r"^(.+): (\d+) completed / (\d+) partial / (\d+) skipped / (\d+) failed$"
)
_COLORS = ("#dcfce7", "#fef3c7", "#e2e8f0", "#fee2e2")
_INKS = ("#166534", "#92400e", "#334155", "#991b1b")


class ReportDialog(QDialog):
    """Render saved summaries as tables, with the original text available."""

    def __init__(self, path: Path, content: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Pipeline report — {path.name}")
        self.resize(960, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        title = QLabel("Pipeline report")
        font = title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        source = QLabel(path.name)
        source.setToolTip(str(path))
        source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(source)

        tabs = QTabWidget()
        layout.addWidget(tabs)
        summary = QWidget()
        summary_layout = QVBoxLayout(summary)
        summary_layout.setSpacing(12)
        rows = []
        remaining = []
        # Only parse the summary: diagnostic text can contain arbitrary content.
        in_details = False
        for line in content.splitlines():
            if not in_details and line.startswith("Created: "):
                source.setText(f"{line}  ·  {path.name}")
                continue
            if line == "Experiment details":
                in_details = True
                continue
            if in_details and line == "------------------":
                continue
            match = None if in_details else _COUNTS.fullmatch(line)
            if match:
                rows.append(match.groups())
            elif line != "FITS pipeline report":
                remaining.append(line)

        self.table = QTableWidget(len(rows), 5)
        self.table.setHorizontalHeaderLabels(
            ["Stage", "Completed", "Partial", "Skipped", "Failed"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(100)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setMinimumHeight(38)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if int(value):
                        item.setBackground(QColor(_COLORS[column - 1]))
                        item.setForeground(QColor(_INKS[column - 1]))
                if row == 0 or (column and int(value)):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row, column, item)
        if rows:
            summary_layout.addWidget(self.table, 3)
        else:
            self.table.hide()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText("\n".join(remaining).strip())
        if self.details.toPlainText():
            summary_layout.addWidget(QLabel("Experiment details" if in_details else "Report notes"))
            summary_layout.addWidget(self.details, 2)
        tabs.addTab(summary, "Overview")
        original = QPlainTextEdit()
        original.setReadOnly(True)
        original.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        original.setPlainText(content)
        tabs.addTab(original, "Original text")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
