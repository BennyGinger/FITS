"""Simple document icons, wrapped filenames and distinct file-action arrows."""

from html import escape
from pathlib import Path
import re
import textwrap

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem

from fits.gui.file_preview.models import COLORS
from fits.gui.file_preview.overview import OverviewStage


CARD_WIDTH = 190
COLUMN_SPACING = 260


def wrapped_filename(name: str, width: int = 18) -> str:
    """
    Prefer line breaks after underscores and split exceptionally long components.
    """
    lines: list[str] = []
    current = ''
    for part in re.split(r'(?<=_)', name):
        if current and len(current + part) > width:
            lines.append(current)
            current = ''
        suffix = Path(part).suffix
        if suffix and len(part) > width:
            chunks = textwrap.wrap(part[:-len(suffix)], width=width, break_on_hyphens=False) or ['']
            if len(chunks[-1] + suffix) <= width:
                chunks[-1] += suffix
            else:
                chunks.append(suffix)
        else:
            chunks = textwrap.wrap(part, width=width, break_on_hyphens=False) or ['']
        for chunk in chunks[:-1]:
            lines.append(current + chunk)
            current = ''
        current += chunks[-1]
    if current:
        lines.append(current)
    return '\n'.join(lines)


def _label(scene: QGraphicsScene, card: QGraphicsRectItem, html: str, y: float, size: int) -> QGraphicsTextItem:
    """
    Add centered text that leaves file selection to its containing item.
    """
    label = scene.addText('')
    label.setParentItem(card)
    font = label.font()
    font.setPixelSize(size)
    label.setFont(font)
    label.setDefaultTextColor(QColor('#eeeeee'))
    label.setTextWidth(CARD_WIDTH)
    label.setHtml(f'<div align="center">{html}</div>')
    label.setPos(0, y)
    label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    return label


def add_stage(scene: QGraphicsScene, item: OverviewStage, x: float, y: float) -> QGraphicsRectItem:
    """
    Draw a generic stage icon, action counts and shared rename patterns.
    """
    card = QGraphicsRectItem()
    card.setPos(x, y)
    card.setPen(QPen(Qt.PenStyle.NoPen))
    card.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
    card.setData(0, item.key)
    card.setData(1, item)
    card.setToolTip(f'{item.title} — {item.file_count}\n{item.count_summary}\nClick to list the files and individual actions.')
    scene.addItem(card)
    heading = _label(scene, card, f'<b>{escape(item.title)}</b>', 0, 18)
    top = heading.boundingRect().bottom() + 10
    card.setData(2, top + 43)
    document = QPainterPath()
    document.moveTo(59, top)
    document.lineTo(110, top)
    document.lineTo(131, top + 21)
    document.lineTo(131, top + 87)
    document.lineTo(59, top + 87)
    document.closeSubpath()
    document.moveTo(110, top)
    document.lineTo(110, top + 21)
    document.lineTo(131, top + 21)
    color = COLORS[item.action]
    pen = QPen(QColor(color), 2)
    if item.action == 'create':
        pen.setStyle(Qt.PenStyle.DashLine)
    icon = scene.addPath(document, pen, QColor('#2a3037'))
    icon.setParentItem(card)
    icon.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    count = _label(scene, card, f'<b>{item.file_count}</b>', top + 96, 14)
    bottom = count.y() + count.boundingRect().height()
    if item.title != 'Original':
        renamed = {new for _, new, _ in item.renames}
        names = {file.path.name for file in item.files}
        for name in sorted(names - renamed) if len(names) == 1 else ():
            filename = escape(wrapped_filename(name)).replace('\n', '<br>')
            label = _label(scene, card, f'<i>{filename}</i>', bottom + 4, 13)
            bottom = label.y() + label.boundingRect().height()
        for old, new, total in item.renames:
            before = escape(wrapped_filename(old)).replace('\n', '<br>')
            after = escape(wrapped_filename(new)).replace('\n', '<br>')
            html = f'<i><s>{before}</s><br>↓<br>{after}</i><br><small>{total} renamed</small>'
            label = _label(scene, card, html, bottom + 4, 13)
            bottom = label.y() + label.boundingRect().height()
    status = _label(scene, card, f'<span style="color:{color}">{escape(item.count_summary)}</span>', bottom + 2, 13)
    card.setRect(0, 0, CARD_WIDTH, status.y() + status.boundingRect().height() + 8)
    if item.action == 'create':
        _insertion_arrow(scene, card, top + 43)
    return card


def _insertion_arrow(scene: QGraphicsScene, card: QGraphicsRectItem, y: float) -> None:
    """
    Mark a new file's insertion into its displayed destination folder.
    """
    pen = QPen(QColor(COLORS['create']), 2, Qt.PenStyle.DashLine)
    line = scene.addLine(14, y, 52, y, pen)
    line.setParentItem(card)
    line.setToolTip('Create the listed files at this stage')
    head = scene.addPolygon(QPolygonF([QPointF(52, y), QPointF(44, y - 4), QPointF(44, y + 4)]), pen, QColor(COLORS['create']))
    head.setParentItem(card)


def add_arrow(scene: QGraphicsScene,
              source: QGraphicsRectItem,
              target: QGraphicsRectItem,
              *,
              geometry_only: bool = False,
              planned: bool = False,
              chronology: bool = False,
              ) -> None:
    """
    Distinguish recorded inputs, proposed processing and geometry-only dependencies.
    """
    first, second = source.sceneBoundingRect(), target.sceneBoundingRect()
    start = QPointF(first.right(), first.top() + source.data(2))
    end = QPointF(second.left(), second.top() + target.data(2))
    path = QPainterPath(start)
    if geometry_only:
        start = QPointF(first.center().x(), first.bottom())
        path = QPainterPath(start)
        path.lineTo(start.x(), end.y())
        path.lineTo(end)
    elif first.left() >= second.left() or end.x() - start.x() > 100:
        above = min(first.top(), second.top()) - 35
        path.lineTo(start.x() + 12, start.y())
        path.lineTo(start.x() + 12, above)
        path.lineTo(end.x() - 12, above)
        path.lineTo(end.x() - 12, end.y())
        path.lineTo(end)
    else:
        middle = (start.x() + end.x()) / 2
        path.cubicTo(middle, start.y(), middle, end.y(), end.x(), end.y())
    color = QColor('#c9d9e8' if chronology else '#78bdb4' if geometry_only else '#91a7bb')
    pen = QPen(color, 2.5 if chronology else 1.5)
    if geometry_only or (planned and not chronology):
        pen.setStyle(Qt.PenStyle.DashLine)
    line = scene.addPath(path, pen)
    line.setZValue(-1)
    line.setData(0, 'workflow-order' if chronology else 'dependency')
    line.setToolTip('Workflow order; this does not assert a saved input relationship' if chronology else
                    'Geometry dependency; registration changes require review' if geometry_only else
                    'Planned processing input' if planned else 'Saved input relationship')
    scene.addPolygon(QPolygonF([end, end + QPointF(-8, -4), end + QPointF(-8, 4)]), QPen(color), color).setZValue(-1)

