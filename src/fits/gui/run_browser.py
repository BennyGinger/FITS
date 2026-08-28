from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Signal, Slot
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QFileSystemModel,
    QLabel,
    QTreeView,
    QVBoxLayout,
    QWidget,
)


class DirectoryBrowser(QWidget):
    """Tree browser rooted inside a selected directory."""

    path_selected = Signal(object)

    def __init__(self,
                 title: str = "Directory contents",
                 file_name_filters: tuple[str, ...] | None = None,
                 parent: QWidget | None = None,
                 ) -> None:
        super().__init__(parent)
        self._root_path: Path | None = None
        self._selected_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        layout.addWidget(self.title_label)

        self.model = QFileSystemModel(self)
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
        layout.addWidget(self.tree)

        self.selection_label = QLabel("")
        self.selection_label.setWordWrap(True)
        self.selection_label.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(self.selection_label)
        self.tree.setModel(self.empty_model)
        self.selection_label.hide()

    @property
    def root_path(self) -> Path | None:
        return self._root_path

    @property
    def selected_path(self) -> Path | None:
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
        selected = Path(self.model.filePath(index)).resolve()
        if selected == self._selected_path:
            self.tree.clearSelection()
            self.tree.setCurrentIndex(QModelIndex())
            self._selected_path = None
            self.selection_label.clear()
            self.selection_label.hide()
            self.path_selected.emit(None)
            return

        self._set_selected_path(selected)

    def _set_selected_path(self, selected: Path) -> None:
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


class RunDirectoryBrowser(DirectoryBrowser):
    """Tree browser rooted inside the selected FITS run directory."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Run directory contents", parent=parent)
