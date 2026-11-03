"""File-level impact diagrams built from the existing preflight inventory."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QShowEvent, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox, QGraphicsItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from fits.environment import constant as cst
from fits.gui.settings.layouts import STEP_LAYOUTS
from fits.workflows.artifacts.branch_masks import geometry, is_branch
from fits.workflows.checks.models import ArtifactRecord, PreflightReport


Role = Literal["input", "selected", "affected", "conflict", "planned"]
_COLORS: dict[Role, tuple[str, str]] = {
    "input": ("#29323b", "#718191"),
    "selected": ("#583311", "#ffad42"),
    "affected": ("#4a4020", "#ebcb65"),
    "conflict": ("#512930", "#ef8c98"),
    "planned": ("#4a4020", "#ebcb65"),
}
_CAPTIONS: dict[Role, str] = {
    "input": "Input / unchanged",
    "selected": "Rerun / overwrite",
    "affected": "Affected downstream",
    "conflict": "Existing conflict",
    "planned": "Included if rebuilding",
}
_STEP_ORDER = {str(step): index for index, step in enumerate(cst.WORKFLOW_ORDER)}
_STEP_LABELS = {str(step): layout.title for step, layout in STEP_LAYOUTS.items()}


@dataclass(frozen=True)
class LineageNode:
    """Describe one displayed file and its preflight impact category."""

    path: Path
    step: str | None
    role: Role
    problem: str = ""
    new_output: bool = False
    legacy: bool = False


@dataclass(frozen=True)
class FileLineage:
    """Keep recorded file relationships separate from planned rebuild outputs."""

    nodes: tuple[LineageNode, ...]
    edges: tuple[tuple[Path, Path], ...]
    geometry_edges: tuple[tuple[Path, Path], ...] = ()


def _registration_will_change(report: PreflightReport, directory: Path) -> bool:
    """
    Identify registration stages included in this experiment's possible rerun.
    """
    registration = {cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME}
    present = {record.step for record in report.records if record.path.resolve().parent == directory}
    planned = {step for step, path in report.rebuild_outputs if path.resolve().parent == directory}
    return bool(registration & (planned | (present & (set(report.overwritten) | set(report.affected)))))


def _geometry_input(record: ArtifactRecord, records: dict[Path, ArtifactRecord]) -> Path | None:
    """
    Attach manual drawings to image geometry rather than intensity processing.
    """
    stages = {cst.StepName.CONVERT, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME}
    candidates = [candidate for candidate in records.values()
                  if candidate.path.resolve().parent == record.path.resolve().parent and candidate.step in stages]
    if not candidates:
        candidates = [candidate for candidate in records.values()
                      if candidate.path.resolve().parent == record.path.resolve().parent
                      and candidate.path.name == cst.FITS_ARRAY_NAME]
    if record.metadata is not None:
        matching = [candidate for candidate in candidates if candidate.metadata is not None
                    and geometry(candidate.metadata) == geometry(record.metadata)]
        if matching:
            candidates = matching
    if not candidates:
        return None
    source = max(candidates, key=lambda candidate: _STEP_ORDER.get(candidate.step or "", -1))
    return source.path.resolve()


def _record_node(record: ArtifactRecord, report: PreflightReport, planned: set[Path]) -> LineageNode:
    """
    Assign impact from the report without inventing additional downstream work.
    """
    path = record.path.resolve()
    role: Role = "input"
    if record.legacy:
        role = "conflict"
    elif is_branch(path):
        if record.problem:
            role = "conflict"
        elif _registration_will_change(report, path.parent):
            role = "affected"
    elif record.step in report.overwritten:
        role = "selected"
    elif record.step in report.affected:
        role = "affected"
    elif record.problem:
        role = "conflict"
    elif path in planned:
        role = "planned"
    return LineageNode(path, record.step, role, record.problem, legacy=record.legacy)


def file_lineage(report: PreflightReport, directory: Path) -> FileLineage:
    """
    Collect one experiment's files, actual recorded ancestors and rebuild outputs.
    """
    directory = directory.resolve()
    records = {record.path.resolve(): record for record in report.records}
    planned = {path.resolve() for _, path in report.rebuild_outputs}
    pending = [record for path, record in records.items() if path.parent == directory]
    nodes = {record.path.resolve(): _record_node(record, report, planned) for record in pending}
    edges: set[tuple[Path, Path]] = set()
    geometry_edges: set[tuple[Path, Path]] = set()
    visited: set[Path] = set()
    while pending:
        record = pending.pop()
        target = record.path.resolve()
        if target in visited:
            continue
        visited.add(target)
        if is_branch(record.path):
            source = _geometry_input(record, records)
            if source is not None:
                geometry_edges.add((source, target))
                if source not in nodes:
                    nodes[source] = _record_node(records[source], report, planned)
                    pending.append(records[source])
            continue
        refs = record.metadata.fits_io.derived_from if record.metadata is not None else None
        if not isinstance(refs, list):
            continue
        for ref in refs:
            relative = ref.get("artifact_path")
            if not isinstance(relative, str):
                continue
            source = (record.path.parent / relative).resolve()
            if source == target:
                continue
            edges.add((source, target))
            if source not in nodes:
                ancestor = records.get(source)
                nodes[source] = (_record_node(ancestor, report, planned) if ancestor is not None
                                 else LineageNode(source, None, "input"))
                if ancestor is not None:
                    pending.append(ancestor)
    for step, output in report.rebuild_outputs:
        path = output.resolve()
        if path.parent == directory and path not in nodes:
            role: Role = "affected" if step in report.affected else "planned"
            nodes[path] = LineageNode(path, step, role, new_output=True)
    return FileLineage(tuple(nodes.values()), tuple(sorted(edges)), tuple(sorted(geometry_edges)))


def _node_order(node: LineageNode) -> tuple[int, str]:
    """
    Arrange files by workflow stage without asserting any unrecorded dependency.
    """
    return (_STEP_ORDER.get(node.step or "", -1), str(node.path))


def _node_caption(node: LineageNode) -> str:
    """
    Distinguish preserved older files and prospective outputs from current overwrites.
    """
    if node.legacy:
        return "Earlier-version result (preserved)"
    if node.new_output:
        return "New output if rebuilding"
    if is_branch(node.path):
        return "Review after registration" if node.role == "affected" else (
            "Geometry needs review" if node.role == "conflict" else "Unchanged / geometry only")
    return _CAPTIONS[node.role]


def _add_node(scene: QGraphicsScene, node: LineageNode, x: float, y: float) -> QGraphicsRectItem:
    """
    Draw a selectable file card with a textual status as well as impact colors.
    """
    background, accent = _COLORS[node.role]
    caption = _node_caption(node)
    step = ("REF / ROI drawing (preserved)" if is_branch(node.path)
            else _STEP_LABELS.get(node.step or "", "Recorded input"))
    card = QGraphicsRectItem()
    card.setPos(x, y)
    card.setBrush(QColor(background))
    pen = QPen(QColor(accent), 2 if node.role != "input" else 1)
    if node.new_output:
        pen.setStyle(Qt.PenStyle.DashLine)
    card.setPen(pen)
    card.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
    card.setData(0, node.path)
    card.setData(1, node)
    card.setToolTip(f"{node.path}\n{caption}" + (f"\n{node.problem}" if node.problem else ""))
    scene.addItem(card)
    text = scene.addText("")
    text.setParentItem(card)
    font = text.font()
    font.setPixelSize(16)
    text.setFont(font)
    text.setHtml(f'<b>{escape(node.path.name)}</b><br>'
                 f'<span style="color:{accent}">{escape(caption)}</span><br>'
                 f'<span style="color:#c5cbd0">{escape(step)}</span>')
    text.setDefaultTextColor(QColor("#eeeeee"))
    text.setTextWidth(204)
    text.setPos(8, 6)
    text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    card.setRect(0, 0, 220, max(78, text.boundingRect().height() + 12))
    return card


def _add_arrow(scene: QGraphicsScene, source: QGraphicsRectItem, target: QGraphicsRectItem,
               *, geometry_only: bool = False,
               ) -> None:
    """
    Connect neighboring stages directly and route longer links above the flow.
    """
    first, second = source.sceneBoundingRect(), target.sceneBoundingRect()
    path = QPainterPath()
    if geometry_only:
        start, end = QPointF(first.center().x(), first.bottom()), QPointF(second.left(), second.center().y())
        path.moveTo(start)
        path.lineTo(start.x(), end.y())
        path.lineTo(end)
        direction = -1
    elif first.left() < second.left():
        start, end = QPointF(first.right(), first.center().y()), QPointF(second.left(), second.center().y())
        path.moveTo(start)
        if second.left() - first.right() > 100:
            above = min(first.top(), second.top()) - 40
            path.lineTo(start.x() + 20, start.y())
            path.lineTo(start.x() + 20, above)
            path.lineTo(end.x() - 20, above)
            path.lineTo(end.x() - 20, end.y())
            path.lineTo(end)
        else:
            middle = (start.x() + end.x()) / 2
            path.cubicTo(middle, start.y(), middle, end.y(), end.x(), end.y())
        direction = -1
    else:
        start, end = QPointF(first.right(), first.center().y()), QPointF(second.right(), second.center().y())
        path.moveTo(start)
        outside = max(start.x(), end.x()) + 40
        path.cubicTo(outside, start.y(), outside, end.y(), end.x(), end.y())
        direction = 1
    node = target.data(1)
    color = (_COLORS[node.role][1] if isinstance(node, LineageNode) and node.role in ("selected", "affected")
             else "#78bdb4" if geometry_only else "#91a7bb")
    pen = QPen(QColor(color), 2 if geometry_only else 1.5)
    if geometry_only:
        pen.setStyle(Qt.PenStyle.DashLine)
    line = scene.addPath(path, pen)
    line.setZValue(-1)
    line.setToolTip("Geometry dependency only; intensity changes do not affect this drawing" if geometry_only
                    else "Saved input relationship")
    head = QPolygonF([end, end + QPointF(direction * 8, -4), end + QPointF(direction * 8, 4)])
    scene.addPolygon(head, QPen(QColor(color)), QColor(color)).setZValue(-1)


class _LineageView(QGraphicsView):
    """Keep ordinary scrolling and support Ctrl+scroll zoom around the cursor."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        """
        Zoom with Ctrl and leave ordinary wheel movement to the scroll bars.
        """
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                factor = 1.25 ** (delta / 120)
                self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)


class ArtifactLineageWidget(QWidget):
    """Show recorded lineage and proposed file impact for one experiment at a time."""

    def __init__(self,
                 report: PreflightReport,
                 parent: QWidget | None = None,
                 *,
                 compact: bool = False,
                 ) -> None:
        """
        Build an experiment selector, zoomable impact map and file-detail area.
        """
        super().__init__(parent)
        self._report = report
        self._nodes: dict[Path, LineageNode] = {}
        self._initial_fit_done = False
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Experiment"))
        self.experiments = QComboBox()
        self.experiments.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.experiments.setMinimumContentsLength(20)
        directories = {record.path.resolve().parent for record in report.records}
        directories.update(path.resolve().parent for _, path in report.rebuild_outputs)
        for directory in sorted(directories):
            self.experiments.addItem(str(directory), directory)
            self.experiments.setItemData(self.experiments.count() - 1, str(directory), Qt.ItemDataRole.ToolTipRole)
        toolbar.addWidget(self.experiments, 1)
        self.scene = QGraphicsScene(self)
        self.view = _LineageView(self.scene)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setToolTip("Ctrl+scroll to zoom; drag to pan.")
        self.view.setBackgroundBrush(QColor("#20262d"))
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        for title, action in (("−", lambda: self.view.scale(.8, .8)),
                              ("Fit", self._fit),
                              ("+", lambda: self.view.scale(1.25, 1.25))):
            button = QPushButton(title)
            button.setToolTip("Fit the complete diagram" if title == "Fit" else "Zoom the file diagram")
            button.clicked.connect(action)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        if report.legacy:
            guidance = "Earlier-version results are preserved. Rebuilding creates current-version results from the original acquisitions."
        elif compact:
            guidance = "Affected results are updated only if you choose rebuild before compacting; choosing keep retains them."
        elif report.overwritten:
            guidance = ("Orange files are selected for overwrite. Amber downstream files are rebuilt only with "
                        "‘Selected step and downstream’; ‘Selected step only’ keeps them and can leave conflicts.")
        else:
            guidance = "Highlighted files have conflicts or are included in the rebuild plan. Continuing without rebuilding retains existing results."
        explanation = QLabel(guidance)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(self.view, 1)
        note = QLabel("Solid arrows show saved inputs; dashed arrows show REF/ROI geometry dependencies. "
                      "Intensity changes leave these drawings unchanged; registration reruns require review. "
                      "Dashed boxes are planned outputs. Ctrl+scroll to zoom; drag to pan.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.details = QLabel("Click a file to see its full path and conflict reason.")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        self.scene.selectionChanged.connect(self._selection_changed)
        self.experiments.currentIndexChanged.connect(self._show_experiment)
        self._show_experiment()

    def showEvent(self, event: QShowEvent) -> None:
        """
        Fit the first overview once the dialog has assigned its actual view size.
        """
        super().showEvent(event)
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QTimer.singleShot(0, self._fit)

    def _show_experiment(self) -> None:
        """
        Arrange workflow stages from left to right, stacking parallel files vertically.
        """
        self.scene.clear()
        directory = self.experiments.currentData()
        if not isinstance(directory, Path):
            self.scene.addText("No file lineage is available in this report.")
            return
        graph = file_lineage(self._report, directory)
        self._nodes = {node.path: node for node in graph.nodes}
        stages: dict[int, list[LineageNode]] = {}
        for node in graph.nodes:
            if is_branch(node.path):
                continue
            # Independent analyses branch from their inputs rather than each other.
            step = str(cst.StepName.EXTRACT) if node.step == cst.StepName.DISTANCE_PROFILE else node.step
            stage = _STEP_ORDER.get(step or "", -1)
            stages.setdefault(stage, []).append(node)
        cards: dict[Path, QGraphicsRectItem] = {}
        for column, stage in enumerate(sorted(stages)):
            x, y = column * 280.0, 0.0
            for node in sorted(stages[stage], key=_node_order):
                card = _add_node(self.scene, node, x, y)
                cards[node.path] = card
                y += card.rect().height() + 28
        branch_y = max((card.sceneBoundingRect().bottom() for card in cards.values()), default=0) + 120
        geometry_inputs = {target: source for source, target in graph.geometry_edges}
        for node in sorted((node for node in graph.nodes if is_branch(node.path)), key=_node_order):
            source_path = geometry_inputs.get(node.path)
            source_card = cards.get(source_path) if source_path is not None else None
            x = source_card.x() + 280 if source_card is not None else 280
            card = _add_node(self.scene, node, x, branch_y)
            cards[node.path] = card
            branch_y += card.rect().height() + 50
        for source, target in graph.edges:
            _add_arrow(self.scene, cards[source], cards[target])
        for source, target in graph.geometry_edges:
            _add_arrow(self.scene, cards[source], cards[target], geometry_only=True)
        for node in graph.nodes:
            if node.role == "selected":
                card = cards[node.path]
                marker = self.scene.addText("↓ RERUN THIS FILE")
                font = marker.font()
                font.setPixelSize(18)
                font.setBold(True)
                marker.setFont(font)
                marker.setDefaultTextColor(QColor(_COLORS["selected"][1]))
                marker.setPos(card.x(), card.y() - marker.boundingRect().height() - 12)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-16, -12, 56, 16))
        self.details.setText("Click a file to see its full path and conflict reason.")
        self._fit()

    def _fit(self) -> None:
        """
        Fit the diagram into the view; zoom buttons retain access to longer filenames.
        """
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _selection_changed(self) -> None:
        """
        Show the selected file's exact path, impact and diagnostic message.
        """
        selected = self.scene.selectedItems()
        if not selected:
            return
        node = self._nodes.get(selected[0].data(0))
        if node is not None:
            message = f"{node.path}\n{_node_caption(node)}"
            if node.problem:
                message += "\n" + node.problem
            self.details.setText(message)
