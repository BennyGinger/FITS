"""Small native icons for backup actions."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF


def restore_icon(colour: QColor) -> QIcon:
    """
    Draw a clock with a backward arrow for restoring a saved version.
    """
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(colour, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawArc(QRectF(4, 4, 16, 16), -50 * 16, 280 * 16)
    painter.drawPolyline(QPolygonF([QPointF(3, 5), QPointF(3, 11), QPointF(9, 11)]))
    painter.drawLine(QPointF(12, 7), QPointF(12, 12))
    painter.drawLine(QPointF(12, 12), QPointF(16, 14))
    painter.end()
    return QIcon(pixmap)
