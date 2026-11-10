from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from PySide6.QtCore import QRectF, QSize, QObject, QPersistentModelIndex, QDir, QModelIndex, Qt, Signal, Slot
from fits.workflows.checks.models import RunCompatibility
from fits.workflows.experiments import ExperimentState
from fits.workflows.experiments.exclusion import selected_experiments
from pathlib import Path
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QApplication, QFileSystemModel, QHBoxLayout, QLabel, QPushButton, QStyle, QTreeView, QVBoxLayout, QWidget


COMPATIBLE_COLOR = '#94cda6'
OUTDATED_COLOR = '#efb366'


class _StatusFileSystemModel(QFileSystemModel):
    """Decorate experiment folders without changing filesystem selection indexes."""

    def __init__(self, parent: QObject | None = None) -> None:
        """
        Initialize the _StatusFileSystemModel state and dependencies.
        """
        super().__init__(parent)
        self.folder_status: dict[Path, bool] = {}
        self.outdated_files: set[Path] = set()
        self.folder_exclusion: dict[Path, tuple[int, int]] = {}
        self._badge_icons: dict[tuple[int, bool], QIcon] = {}
        self.highlighted_paths: set[Path] = set()

    def data(self,
             index: QModelIndex | QPersistentModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole,
             ) -> Any:
        """
        Return the model value for the requested index and display role.
        """
        if index.isValid() and index.column() == 0:
            folder = Path(self.filePath(index))
            if folder in self.highlighted_paths:
                if role == Qt.ItemDataRole.BackgroundRole:
                    return QApplication.palette().color(QPalette.ColorRole.Highlight)
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QApplication.palette().color(QPalette.ColorRole.HighlightedText)
            excluded, total = self.folder_exclusion.get(folder, (0, 0))
            if excluded:
                if role == Qt.ItemDataRole.ForegroundRole and excluded == total:
                    return QColor('#999999')
                if role == Qt.ItemDataRole.DecorationRole:
                    base = super().data(index, role)
                    if isinstance(base, QIcon):
                        return self._exclusion_icon(base, excluded == total)
                if role == Qt.ItemDataRole.ToolTipRole:
                    return ('Excluded from processing and analysis' if excluded == total else
                            f'{excluded} of {total} experiments excluded')
            outdated = True if folder in self.outdated_files else self.folder_status.get(folder)
            if outdated is not None:
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QColor(OUTDATED_COLOR if outdated else COMPATIBLE_COLOR)
                if role == Qt.ItemDataRole.DecorationRole and outdated and self.isDir(index):
                    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
                if role == Qt.ItemDataRole.ToolTipRole:
                    return ('Experiment files need attention. See Manage files for migration, rebuilding or path/tag updates.' if outdated else
                            'Compatible experiment files. Processing availability follows the whole run status.')
        return super().data(index, role)

    def highlight_paths(self, paths: set[Path]) -> None:
        """
        Highlight one ancestry branch without adding parents to the actual selection.
        """
        changed = self.highlighted_paths.symmetric_difference(paths)
        self.highlighted_paths = paths
        for path in changed:
            index = self.index(str(path))
            if index.isValid():
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole])


    def _exclusion_icon(self, base: QIcon, fully_excluded: bool) -> QIcon:
        """
        Overlay a circle-minus or amber half-circle on the existing folder icon.
        """
        if base.isNull():
            base = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        key = (base.cacheKey(), fully_excluded)
        if key not in self._badge_icons:
            pixmap = base.pixmap(24, 24)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            bounds = QRectF(12, 12, 11, 11)
            color = QColor('#999999' if fully_excluded else OUTDATED_COLOR)
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(QColor('#303030'))
            painter.drawEllipse(bounds)
            if fully_excluded:
                painter.drawLine(15, 18, 20, 18)
            else:
                painter.setBrush(color)
                painter.drawPie(bounds, 90 * 16, 180 * 16)
            painter.end()
            self._badge_icons[key] = QIcon(pixmap)
        return self._badge_icons[key]


class DirectoryBrowser(QWidget):
    """Tree browser rooted inside a selected directory."""

    path_selected = Signal(object)
    path_activated = Signal(object)

    def __init__(self,
                 title: str = "Directory contents",
                 file_name_filters: tuple[str, ...] | None = None,
                 parent: QWidget | None = None,
                 *,
                 highlight_selection_path: bool = False,
                 ) -> None:
        """
        Initialize the DirectoryBrowser state and dependencies.
        """
        super().__init__(parent)
        self._root_path: Path | None = None
        self._selected_path: Path | None = None
        self._highlight_selection_path = highlight_selection_path

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
        if highlight_selection_path:
            palette = QApplication.palette()
            background = palette.color(QPalette.ColorRole.Highlight).name()
            foreground = palette.color(QPalette.ColorRole.HighlightedText).name()
            base = palette.color(QPalette.ColorRole.Base).name()
            self.tree.setStyleSheet("QTreeView { show-decoration-selected: 0; } "
                                   f"QTreeView::branch:selected {{ background: {base}; }} "
                                   f"QTreeView::item:selected {{ background: {background}; color: {foreground}; }}")
        self.tree.setSortingEnabled(False)
        for column in range(1, self.model.columnCount()):
            self.tree.hideColumn(column)
        self.tree.clicked.connect(self._on_clicked)
        self.tree.doubleClicked.connect(self._on_activated)
        layout.addWidget(self.tree)

        selection_row = QHBoxLayout()
        self.selection_path_layout = selection_row
        self.selection_label = QLabel("")
        self.selection_label.setWordWrap(True)
        self.selection_label.setStyleSheet("color: #b8b8b8;")
        selection_row.addWidget(self.selection_label, 1)
        layout.addLayout(selection_row)
        self.selection_layout = QHBoxLayout()
        layout.addLayout(self.selection_layout)
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
            self.model.highlight_paths(set())
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
        self.selection_label.setVisible(not self._highlight_selection_path)
        self._highlight_path(root)
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
            self.model.highlight_paths(set())
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
        self.selection_label.setVisible(not self._highlight_selection_path)
        self._highlight_path(selected)
        self.path_selected.emit(selected)

    def _highlight_path(self, selected: Path) -> None:
        """
        Reveal the experiment branch inside viewer browsers instead of wrapping its path.
        """
        if not self._highlight_selection_path or self._root_path is None:
            return
        paths = {selected}
        parent = selected if selected.is_dir() else selected.parent
        while parent == self._root_path or self._root_path in parent.parents:
            paths.add(parent)
            index = self.model.index(str(parent))
            if index.isValid() and index != self.tree.rootIndex():
                self.tree.expand(index)
            if parent == self._root_path:
                break
            parent = parent.parent
        self.model.highlight_paths(paths)

    @Slot(QModelIndex)
    def _on_activated(self, index: QModelIndex) -> None:
        """
        Handle activated.
        """
        self.path_activated.emit(Path(self.model.filePath(index)).resolve())


class RunDirectoryBrowser(DirectoryBrowser):
    """Tree browser rooted inside the selected FITS run directory."""

    exclusion_requested = Signal(object, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize the RunDirectoryBrowser state and dependencies.
        """
        super().__init__("Run directory contents", parent=parent)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setIconSize(QSize(24, 24))
        self._states: tuple[ExperimentState, ...] = ()
        self._processing = False
        self.exclusion_button = QPushButton('Exclude experiments')
        self.exclusion_button.setEnabled(False)
        self.exclusion_button.clicked.connect(self._request_exclusion)
        self.selection_path_layout.addWidget(self.exclusion_button)

    def set_root(self, path: str | Path) -> None:
        """
        Reconnect selection updates when the filesystem model replaces the empty model.
        """
        previous = self.tree.selectionModel()
        super().set_root(path)
        current = self.tree.selectionModel()
        if current is not previous:
            current.selectionChanged.connect(self._refresh_exclusion_action)
        self._refresh_exclusion_action()

    def set_processing(self, running: bool) -> None:
        """
        Keep inclusion fixed while a pipeline is running.
        """
        self._processing = running
        self._refresh_exclusion_action()

    def selected_folders(self) -> list[Path]:
        """
        Return only explicitly selected filesystem directories.
        """
        if self.tree.model() is not self.model:
            return []
        return [Path(self.model.filePath(index)) for index in self.tree.selectionModel().selectedRows()
                if self.model.isDir(index)]

    def _refresh_exclusion_action(self) -> None:
        """
        Set one unambiguous action for active, excluded and mixed selections.
        """
        states = selected_experiments(self._states, self.selected_folders())
        excluded = sum(state.excluded for state in states)
        self.exclusion_button.setText('Re-include experiments' if states and excluded == len(states) else
                                      'Exclude experiments')
        eligible = bool(states) and all(state.migration_checkpoint is None for state in states)
        self.exclusion_button.setEnabled(eligible and not self._processing)
        self.exclusion_button.setToolTip('Exclude from processing and analysis; existing files remain inspectable.' if eligible else
                                         'Select converted experiments. Migrated results require a full rebuild first.')

    def _request_exclusion(self) -> None:
        """
        Request one inclusion value for the selected experiment folders.
        """
        if self.exclusion_button.isEnabled():
            states = selected_experiments(self._states, self.selected_folders())
            self.exclusion_requested.emit(self.selected_folders(), not all(state.excluded for state in states))

    def set_experiment_status(self, status: RunCompatibility | None,
                               conflicts: Iterable[Path] = (),
                               outdated_files: Iterable[Path] = (),
                               ) -> None:
        """
        Decorate folders and outdated files using the shared checker's inventory.
        """
        folders = {}
        exclusion: dict[Path, tuple[int, int]] = {}
        self._states = status.states if status is not None else ()
        if status is not None:
            for state in status.states:
                current = state.workdir
                while current == status.root or status.root in current.parents:
                    excluded, total = exclusion.get(current, (0, 0))
                    exclusion[current] = (excluded + int(state.excluded), total + 1)
                    if current == status.root:
                        break
                    current = current.parent
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
        previous = self.model.folder_status.keys() | self.model.folder_exclusion.keys() | self.model.outdated_files
        self.model.folder_status = folders
        self.model.folder_exclusion = exclusion
        self.model.outdated_files = set(outdated_files) if status is not None else set()
        self._refresh_exclusion_action()
        for folder in previous | folders.keys() | exclusion.keys() | self.model.outdated_files:
            index = self.model.index(str(folder))
            if index.isValid():
                self.model.dataChanged.emit(index, index, [Qt.ItemDataRole.ForegroundRole,
                    Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.ToolTipRole])
