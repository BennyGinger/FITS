from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from PySide6.QtCore import QObject, QPersistentModelIndex, QDir, QModelIndex, Qt, Signal, Slot
from fits.workflows.checks.models import RunCompatibility
from pathlib import Path
from PySide6.QtGui import QColor, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QApplication, QFileSystemModel, QHBoxLayout, QLabel, QStyle, QTreeView, QVBoxLayout, QWidget


COMPATIBLE_COLOR = '#94cda6'
OUTDATED_COLOR = '#efb366'


class _StatusFileSystemModel(QFileSystemModel):
    """Decorate experiment folders without changing filesystem selection indexes."""

    def __init__(self, parent: QObject | None = None) -> None:
        """
        Initialize the _StatusFileSystemModel state and dependencies.
        """
        super().__init__(parent)
        self.folder_status = {}

    def data(self,
             index: QModelIndex | QPersistentModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole,
             ) -> Any:
        """
        Return the model value for the requested index and display role.
        """
        if index.isValid() and index.column() == 0:
            outdated = self.folder_status.get(Path(self.filePath(index)))
            if outdated is not None:
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QColor(OUTDATED_COLOR if outdated else COMPATIBLE_COLOR)
                if role == Qt.ItemDataRole.DecorationRole and outdated:
                    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
                if role == Qt.ItemDataRole.ToolTipRole:
                    return ('Experiment files need attention. See Details and Manage files for migration, rebuilding or path/tag updates.' if outdated else
                            'Compatible experiment files. Processing availability follows the whole run status.')
        return super().data(index, role)


class DirectoryBrowser(QWidget):
    """Tree browser rooted inside a selected directory."""

    path_selected = Signal(object)
    path_activated = Signal(object)

    def __init__(self,
                 title: str = "Directory contents",
                 file_name_filters: tuple[str, ...] | None = None,
                 parent: QWidget | None = None,
                 ) -> None:
        """
        Initialize the DirectoryBrowser state and dependencies.
        """
        super().__init__(parent)
        self._root_path: Path | None = None
        self._selected_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        layout.addWidget(self.title_label)

        self.model = _StatusFileSystemModel(self)
        self.model.setReadOnly(True)
        if file_name_filters is not None:
            self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
            self.model.setNameFilters(list(file_name_filters))
            self.model.setNameFilterDisables(False)
        self.empty_model = QStandardItemModel(self)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(False)
        for column in range(1, self.model.columnCount()):
            self.tree.hideColumn(column)
        self.tree.clicked.connect(self._on_clicked)
        self.tree.doubleClicked.connect(self._on_activated)
        layout.addWidget(self.tree)

        selection_row = QHBoxLayout()
        self.selection_layout = selection_row
        self.selection_label = QLabel("")
        self.selection_label.setWordWrap(True)
        self.selection_label.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(self.selection_label)
        layout.addLayout(selection_row)
        self.tree.setModel(self.empty_model)
        self.selection_label.hide()

    @property
    def root_path(self) -> Path | None:
        """
        Root path.
        """
        return self._root_path

    @property
    def selected_path(self) -> Path | None:
        """
        Selected path.
        """
        return self._selected_path

    def select_path(self, path: str | Path) -> bool:
        """
        Select and reveal an existing path inside the current browser root.
        """
        selected = Path(path).expanduser().resolve()
        if self._root_path is None or not selected.exists():
            return False
        try:
            selected.relative_to(self._root_path)
        except ValueError:
            return False
        index = self.model.index(str(selected))
        if not index.isValid():
            return False
        parent_index = index.parent()
        while parent_index.isValid() and parent_index != self.tree.rootIndex():
            self.tree.expand(parent_index)
            parent_index = parent_index.parent()
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index)
        self._set_selected_path(selected)
        return True

    def set_root(self, path: str | Path) -> None:
        """
        Set root.
        """
        raw_path = str(path).strip()
        root = Path(raw_path).expanduser().resolve() if raw_path else None
        if root == self._root_path:
            return

        if root is None or not root.is_dir():
            self._root_path = None
            self._selected_path = None
            self.tree.setModel(self.empty_model)
            self.selection_label.clear()
            self.selection_label.hide()
            self.path_selected.emit(None)
            return

        self._root_path = root
        self._selected_path = root
        self.tree.setModel(self.model)
        for column in range(1, self.model.columnCount()):
            self.tree.hideColumn(column)
        root_index = self.model.setRootPath(str(root))
        self.tree.setRootIndex(root_index)
        self.tree.collapseAll()
        self.selection_label.setText("Selected: .")
        self.selection_label.show()
        self.path_selected.emit(root)

    @Slot(QModelIndex)
    def _on_clicked(self, index: QModelIndex) -> None:
        """
        Handle clicked.
        """
        selected = Path(self.model.filePath(index)).resolve()
        if (selected == self._selected_path
                and self.tree.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection):
            self.tree.clearSelection()
            self.tree.setCurrentIndex(QModelIndex())
            self._selected_path = None
            self.selection_label.clear()
            self.selection_label.hide()
            self.path_selected.emit(None)
            return

        self._set_selected_path(selected)

    def _set_selected_path(self, selected: Path) -> None:
        """
        Set selected path.
        """
        self._selected_path = selected
        if self._root_path is None:
            label = selected.name
        else:
            try:
                label = str(selected.relative_to(self._root_path))
            except ValueError:
                label = selected.name
        self.selection_label.setText(f"Selected: {label}")
        self.selection_label.show()
        self.path_selected.emit(selected)

    @Slot(QModelIndex)
    def _on_activated(self, index: QModelIndex) -> None:
        """
        Handle activated.
        """
        self.path_activated.emit(Path(self.model.filePath(index)).resolve())


class RunDirectoryBrowser(DirectoryBrowser):
    """Tree browser rooted inside the selected FITS run directory."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize the RunDirectoryBrowser state and dependencies.
        """
        super().__init__("Run directory contents", parent=parent)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def set_experiment_status(self, status: RunCompatibility | None, conflicts: Iterable[Path] = ()) -> None:
        """
        Set experiment status.
        """
        folders = {}
        if status is not None:
            known = {state.workdir for state in status.states}
            known.update(path.parent for path in status.old_states)
            known.update(path.parent for path in status.files)
            known.update(status.outdated_folders)
            known.update(conflicts)
            for folder in known:
                outdated = folder in status.outdated_folders or folder in conflicts
                current = folder
                while current == status.root or status.root in current.parents:
                    folders[current] = folders.get(current, False) or outdated
                    if current == status.root:
                        break
                    current = current.parent
            if status.outdated:
                folders[status.root] = True
        previous = self.model.folder_status
        self.model.folder_status = folders
        for folder in previous.keys() | folders.keys():
            index = self.model.index(str(folder))
            if index.isValid():
                self.model.dataChanged.emit(index, index, [Qt.ItemDataRole.ForegroundRole,
                    Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.ToolTipRole])
