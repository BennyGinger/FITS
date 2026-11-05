"""Whole-run stage diagrams with scrollable per-file action details."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QShowEvent, QWheelEvent
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fits.gui.file_preview.graphics import COLUMN_SPACING, add_arrow, add_stage
from fits.gui.file_preview.models import CURRENT_COLOR, CHANGED_COLOR, CREATED_COLOR, OVERWRITE_COLOR, PreviewGroup
from fits.gui.file_preview.overview import OverviewStage, RunOverview, run_overview
from fits.gui.file_preview.stage_files import StageFilesWidget


class _FileView(QGraphicsView):
    """
    Preserve scrolling and clear details when the diagram background is clicked.
    """

    def wheelEvent(self, event: QWheelEvent) -> None:
        """
        Zoom with Ctrl while retaining normal scrollbar behavior otherwise.
        """
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self.scale(1.25 ** (delta / 120), 1.25 ** (delta / 120))
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """
        Treat only stage icons and their labels as diagram selections.
        """
        item = self.itemAt(event.position().toPoint())
        while item is not None and not isinstance(item.data(1), OverviewStage):
            item = item.parentItem()
        scene = self.scene()
        if item is None and scene is not None:
            scene.clearSelection()
        super().mousePressEvent(event)


def _stage_order(stage: OverviewStage) -> tuple[int, str]:
    """
    Keep current/proposed workflow outputs above superseded files.
    """
    rank = 2 if all(item.action == 'remove' for item in stage.files) else 1 if stage.action == 'keep' else 0
    return rank, stage.title


class FilePreviewWidget(QWidget):
    """
    Show one processing schematic for every experiment in the reviewed run.
    """

    def __init__(self, groups: tuple[PreviewGroup, ...], guidance: str = '', parent: QWidget | None = None) -> None:
        """
        Build a generic run overview, zoom controls and an initially hidden file list.
        """
        super().__init__(parent)
        self._groups = groups
        self.overview = RunOverview((), ())
        self._stages: dict[str, OverviewStage] = {}
        self._initial_view_shown = False
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('Run overview'))
        toolbar.addStretch()
        self.scene = QGraphicsScene(self)
        self.view = _FileView(self.scene)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setToolTip('Ctrl+scroll to zoom; drag to pan.')
        self.view.setBackgroundBrush(QColor('#20262d'))
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        for title, action in (('−', lambda: self.view.scale(.8, .8)), ('Fit', self._fit), ('+', lambda: self.view.scale(1.25, 1.25))):
            button = QPushButton(title)
            button.pressed.connect(self.scene.clearSelection)
            button.clicked.connect(action)
            button.setToolTip('Fit the complete diagram' if title == 'Fit' else 'Zoom the run diagram')
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.guidance = QLabel(guidance)
        self.guidance.setWordWrap(True)
        self.guidance.setVisible(bool(guidance))
        layout.addWidget(self.guidance)
        legend = QLabel(f'<span style="color:{CURRENT_COLOR}">● All kept</span>　'
                        f'<span style="color:{OVERWRITE_COLOR}">● Overwritten / rebuilt</span>　'
                        f'<span style="color:{CHANGED_COLOR}">● Affected / changed</span>　'
                        f'<span style="color:{CREATED_COLOR}">● All new</span>')
        legend.setWordWrap(True)
        layout.addWidget(legend)
        layout.addWidget(self.view, 1)
        note = QLabel('Click a stage to list its files and actions. Arrows show workflow order. Ctrl+scroll: zoom; drag: pan.')
        note.setWordWrap(True)
        note.setToolTip('Counts refer to unique files. Shared rename patterns apply only to the listed files. '
                        'Other arrows preserve saved/proposed inputs and REF/ROI geometry relationships.')
        layout.addWidget(note)
        self.details = StageFilesWidget()
        layout.addWidget(self.details)
        self.details.hide()
        self.scene.selectionChanged.connect(self._selection_changed)
        self.set_groups(groups)

    def set_groups(self, groups: tuple[PreviewGroup, ...], guidance: str | None = None) -> None:
        """
        Refresh the entire run when switching between migration and reconstruction.
        """
        self._groups = groups
        self.overview = run_overview(groups)
        self._stages = {stage.key: stage for stage in self.overview.stages}
        if guidance is not None:
            self.guidance.setText(guidance)
            self.guidance.setVisible(bool(guidance))
        self._show_run()

    def showEvent(self, event: QShowEvent) -> None:
        """
        Show readable full-size icons after the dialog assigns its actual size.
        """
        super().showEvent(event)
        if not self._initial_view_shown:
            self._initial_view_shown = True
            QTimer.singleShot(0, self._show_readable)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """
        Hide the file list when clicking unused space around the diagram.
        """
        self.scene.clearSelection()
        super().mousePressEvent(event)

    def _add_cards(self) -> dict[str, QGraphicsRectItem]:
        """
        Place one icon per role, retaining parallel analyses and manual-mask branches.
        """
        cards: dict[str, QGraphicsRectItem] = {}
        stages = sorted({stage.stage for stage in self.overview.stages if not stage.branch})
        for column, order in enumerate(stages):
            y = 0.0
            for stage in sorted((stage for stage in self.overview.stages if stage.stage == order and not stage.branch), key=_stage_order):
                card = add_stage(self.scene, stage, column * COLUMN_SPACING, y)
                cards[stage.key] = card
                y += card.rect().height() + 24
        branch_y = max((card.sceneBoundingRect().bottom() for card in cards.values()), default=0) + 90
        for stage in (stage for stage in self.overview.stages if stage.branch):
            sources = [cards[link.source] for link in self.overview.links
                       if link.kind == 'geometry' and link.target == stage.key and link.source in cards]
            x = max((card.x() for card in sources), default=0) + COLUMN_SPACING
            card = add_stage(self.scene, stage, x, branch_y)
            cards[stage.key] = card
            branch_y += card.rect().height() + 24
        return cards

    def _show_run(self) -> None:
        """
        Draw the merged workflow and keep full per-file scope in the hidden detail panel.
        """
        self.scene.clear()
        cards = self._add_cards()
        if not cards:
            self.scene.addText('No files are included in this plan.')
        for link in self.overview.links:
            add_arrow(self.scene, cards[link.source], cards[link.target],
                      planned=link.kind == 'planned', chronology=link.kind == 'sequence', geometry_only=link.kind == 'geometry')
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-16, -12, 30, 16))
        self.details.clear()
        self.details.hide()
        self._show_readable()

    def _show_readable(self) -> None:
        """
        Retain designed text sizes and start at the beginning of a long workflow.
        """
        self.view.resetTransform()
        bounds = self.scene.sceneRect()
        self.view.centerOn(bounds.left() + self.view.viewport().width() / 2,
                           bounds.top() + self.view.viewport().height() / 2)

    def _fit(self) -> None:
        """
        Fit the whole run when explicitly requested.
        """
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _selection_changed(self) -> None:
        """
        List a selected stage's actual files, or clear them on background selection.
        """
        selected = self.scene.selectedItems()
        self.details.clear()
        self.details.hide()
        if selected:
            stage = self._stages.get(selected[0].data(0))
            if stage is not None:
                self.details.set_stage(stage)
                self.details.show()
