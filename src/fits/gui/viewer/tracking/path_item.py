"""One graphics item for all trajectory paths in a tracking plane."""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPicture
from PySide6.QtWidgets import QGraphicsObject, QStyleOptionGraphicsItem, QWidget


class TrackPathsItem(QGraphicsObject):
    """Paint many tracks as one cached scene item."""

    def __init__(self) -> None:
        super().__init__()
        self._picture = QPicture()
        self._bounds = QRectF()
        self._x: NDArray[np.float64] = np.empty(0, dtype=np.float64)
        self._y: NDArray[np.float64] = np.empty(0, dtype=np.float64)

    def set_tracks(
        self,
        tracks: dict[int, NDArray[np.float64]],
        *,
        color_for: Callable[[int], QColor],
        thickness: int,
        show_markers: bool,
        marker_size: int,
    ) -> None:
        picture = QPicture()
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        all_x: list[NDArray[np.float64]] = []
        all_y: list[NDArray[np.float64]] = []
        marker_radius = marker_size / 2.0
        for track_id, points in tracks.items():
            if not len(points):
                continue
            color = color_for(track_id)
            pen = QPen(color)
            pen.setWidth(thickness)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(QPointF(float(points[0, 1]), float(points[0, 2])))
            for point in points[1:]:
                path.lineTo(float(point[1]), float(point[2]))
            painter.drawPath(path)
            if show_markers:
                painter.setBrush(QBrush(color))
                for point in points:
                    painter.drawEllipse(
                        QPointF(float(point[1]), float(point[2])),
                        marker_radius,
                        marker_radius,
                    )
            all_x.extend((points[:, 1], np.asarray([np.nan])))
            all_y.extend((points[:, 2], np.asarray([np.nan])))
        painter.end()
        self.prepareGeometryChange()
        self._picture = picture
        self._bounds = QRectF(picture.boundingRect())
        self._x = (np.concatenate(all_x)[:-1] if all_x
                   else np.empty(0, dtype=np.float64))
        self._y = (np.concatenate(all_y)[:-1] if all_y
                   else np.empty(0, dtype=np.float64))
        self.update()

    def getData(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Expose plotted coordinates for inspection and compatibility."""
        return self._x, self._y

    def paint(self,
              painter: QPainter,
              option: QStyleOptionGraphicsItem,
              /,
              widget: QWidget | None = None,
              ) -> None:
        del option, widget
        painter.drawPicture(0, 0, self._picture)

    def boundingRect(self) -> QRectF:
        return self._bounds
