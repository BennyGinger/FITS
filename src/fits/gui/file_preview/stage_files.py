"""Scrollable acquisition/series file lists for selected run-overview stages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QLabel, QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from fits.gui.file_preview.models import CAPTIONS, file_summary
from fits.gui.file_preview.overview import OverviewStage


class StageFilesWidget(QWidget):
    """
    List actual files and their individual actions without crowding the run diagram.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Prepare a compact, scrollable details area that appears only after selection.
        """
        super().__init__(parent)
        self.stage: OverviewStage | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Acquisition / experiment / file', 'Action'])
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree)

    def set_stage(self, stage: OverviewStage) -> None:
        """
        Show each physical file once, grouped by acquisition and series with full-path tooltips.
        """
        self.stage = stage
        self.heading.setText(f'{stage.title} — {stage.file_count}: {stage.count_summary}')
        self.tree.clear()
        acquisitions: dict[str, QTreeWidgetItem] = {}
        series: dict[str, QTreeWidgetItem] = {}
        for item in stage.files:
            original = stage.title == 'Original'
            acquisition = item.path.parent if original else item.path.parent.parent
            acquisition_key = str(acquisition)
            if acquisition_key not in acquisitions:
                title = f'{acquisition.parent.name}/{acquisition.name}'
                row = QTreeWidgetItem(self.tree, [title])
                row.setToolTip(0, acquisition_key)
                acquisitions[acquisition_key] = row
            parent = acquisitions[acquisition_key]
            if not original:
                series_key = str(item.path.parent)
                if series_key not in series:
                    row = QTreeWidgetItem(parent, [item.path.parent.name])
                    row.setToolTip(0, series_key)
                    series[series_key] = row
                parent = series[series_key]
            name = f'{item.source.name} → {item.path.name}' if item.source is not None and item.source.name != item.path.name else item.path.name
            row = QTreeWidgetItem(parent, [name, CAPTIONS[item.action]])
            row.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            row.setData(0, Qt.ItemDataRole.UserRole, item)
            tooltip = f'{item.path}\n{file_summary(item)}'
            if item.source is not None:
                tooltip += f'\nFrom: {item.source}'
            if item.detail:
                tooltip += '\n' + item.detail
            row.setToolTip(0, tooltip)
            row.setToolTip(1, tooltip)
        self.tree.expandAll()
        rows = min(9, len(stage.files) + len(acquisitions) + len(series))
        height = self.tree.header().sizeHint().height() + rows * (self.tree.fontMetrics().height() + 8) + 8
        self.tree.setFixedHeight(min(260, max(90, height)))

    def clear(self) -> None:
        """
        Release the previous stage's details when the diagram background is clicked.
        """
        self.stage = None
        self.heading.clear()
        self.tree.clear()
