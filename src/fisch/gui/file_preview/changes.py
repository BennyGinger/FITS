"""Readable per-file changes for updates that do not need a workflow diagram."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QLabel, QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from fisch.gui.file_preview.models import FileChange


class FileChangesWidget(QWidget):
    """
    Group affected files by destination folder and explain how each is handled.
    """

    def __init__(self, changes: tuple[FileChange, ...], parent: QWidget | None = None) -> None:
        """
        Build a selectable file/action/explanation list with full-path tooltips.
        """
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['File', 'Planned change', 'What changes'])
        self.tree.setWordWrap(True)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 260)
        groups: dict[str, QTreeWidgetItem] = {}
        first: QTreeWidgetItem | None = None
        preferred: QTreeWidgetItem | None = None
        for change in changes:
            folder = str(change.path.parent)
            if folder not in groups:
                group = QTreeWidgetItem([folder])
                group.setFirstColumnSpanned(True)
                self.tree.addTopLevelItem(group)
                groups[folder] = group
            name = change.path.name
            if change.source is not None:
                name = f'{change.source.name} → {name}'
            item = QTreeWidgetItem(groups[folder], [name, change.action, change.detail])
            first = first or item
            if change.action == 'Update paths and tags' and preferred is None:
                preferred = item
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            tooltip = f'{change.source}\n→ {change.path}' if change.source is not None else str(change.path)
            for column in range(3):
                item.setToolTip(column, tooltip + '\n' + change.detail)
            item.setData(0, Qt.ItemDataRole.UserRole, change)
        self.tree.expandAll()
        layout.addWidget(self.tree)
        self.details = QLabel('Select a file to see its full paths and changes.')
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        self.tree.itemSelectionChanged.connect(self._show_change)
        selected = preferred if preferred is not None else first
        if selected is not None:
            self.tree.setCurrentItem(selected)

    def _show_change(self) -> None:
        """
        Keep complete path/tag values readable even when table columns are narrow.
        """
        selected = self.tree.selectedItems()
        change = selected[0].data(0, Qt.ItemDataRole.UserRole) if selected else None
        self.details.clear()
        self.details.hide()
        if isinstance(change, FileChange):
            before = f'{change.source}\n→ ' if change.source is not None else ''
            self.details.setText(f'{before}{change.path}\n{change.action}: {change.detail}')
            self.details.show()
