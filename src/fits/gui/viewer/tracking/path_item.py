"""Prepared trajectory drawings, reused while navigating a tracking movie."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from tempfile import TemporaryFile
import errno
import os

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPicture
from PySide6.QtWidgets import QGraphicsObject, QStyleOptionGraphicsItem, QWidget


@dataclass
class PreparedPaths:
    tracks: dict[int, NDArray[np.float64]]
    bounds: QRectF
    full_image: QImage
    frames: NDArray[np.uint8] | None

    def image(self, frame: int) -> QImage:
        """Wrap an already-drawn disk-backed plane without copying its pixels."""
        if self.frames is None:
            return self.full_image
        pixels = self.frames[min(max(0, frame), len(self.frames) - 1)]
        height, width = pixels.shape[:2]
        return QImage(pixels.data, width, height, width * 4,
                      QImage.Format.Format_ARGB32_Premultiplied)


def _blank(bounds: QRectF) -> QImage:
    image = QImage(max(1, int(bounds.width())), max(1, int(bounds.height())),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return image


def _draw(image: QImage, picture: QPicture, bounds: QRectF) -> None:
    painter = QPainter(image)
    painter.translate(-bounds.left(), -bounds.top())
    painter.drawPicture(0, 0, picture)
    painter.end()


def _frame_storage(count: int, bounds: QRectF) -> NDArray[np.uint8]:
    shape = count, max(1, int(bounds.height())), max(1, int(bounds.width())), 4
    size = int(np.prod(shape, dtype=np.int64))
    with TemporaryFile() as file:
        # Reserve space before mapping, so a full temporary disk raises an error
        # here rather than causing a memory-map fault during drawing.
        if hasattr(os, "posix_fallocate"):
            try:
                os.posix_fallocate(file.fileno(), 0, size)
            except OSError as error:
                if error.errno not in (errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL):
                    raise
                file.truncate(size)
        else:
            file.truncate(size)
        return np.memmap(file, dtype=np.uint8, mode="r+", shape=shape)


def prepare_paths(tracks: dict[int, NDArray[np.float64]], *,
                  color_for: Callable[[int], QColor], thickness: int,
                  show_markers: bool, marker_size: int,
                  progress: Callable[[int, int], None] | None = None,
                  cancelled: Callable[[], bool] | None = None) -> PreparedPaths | None:
    """Draw every frame once into temporary mapped storage off the GUI thread."""
    pictures: dict[int, QPicture] = {}
    painters: dict[int, QPainter] = {}
    frame_count = max((int(points[-1, 0]) + 1 for points in tracks.values() if len(points)), default=0)
    total = len(tracks) + frame_count
    try:
        for number, (track_id, points) in enumerate(tracks.items()):
            if cancelled is not None and cancelled():
                return None
            color = color_for(track_id)
            pen = QPen(color)
            pen.setWidth(thickness)
            previous: QPointF | None = None
            for point in points:
                frame = int(point[0])
                if frame not in pictures:
                    pictures[frame] = QPicture()
                    painters[frame] = QPainter(pictures[frame])
                    painters[frame].setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter = painters[frame]
                painter.setPen(pen)
                position = QPointF(float(point[1]), float(point[2]))
                if previous is not None:
                    painter.drawLine(previous, position)
                if show_markers:
                    painter.setBrush(QBrush(color))
                    painter.drawEllipse(position, marker_size / 2.0, marker_size / 2.0)
                previous = position
            if progress is not None:
                progress(number + 1, total)
    finally:
        for painter in painters.values():
            painter.end()
    bounds = QRectF()
    for picture in pictures.values():
        bounds = bounds.united(QRectF(picture.boundingRect()))
    bounds = bounds.adjusted(-1, -1, 1, 1).toAlignedRect().toRectF()
    image = _blank(bounds)
    frames = _frame_storage(frame_count, bounds) if frame_count else None
    for frame in range(frame_count):
        if cancelled is not None and cancelled():
            return None
        picture = pictures.get(frame)
        if picture is not None:
            _draw(image, picture, bounds)
        assert frames is not None
        pixels = image.constBits()
        assert pixels is not None
        frames[frame] = np.frombuffer(pixels, dtype=np.uint8).reshape(frames.shape[1:])
        if progress is not None:
            progress(len(tracks) + frame + 1, total)
    if frames is not None:
        frames.setflags(write=False)
    prepared = PreparedPaths(tracks, bounds, image, frames)
    if frames is not None:
        prepared.full_image = prepared.image(frame_count - 1)
    return prepared


class TrackPathsItem(QGraphicsObject):
    """Select an already-drawn overlay for any frame without trajectory calculations."""

    def __init__(self) -> None:
        super().__init__()
        self._prepared: PreparedPaths | None = None
        self._image = QImage()
        self._frame = -1
        self._full = True

    def set_prepared(self, prepared: PreparedPaths) -> None:
        self.prepareGeometryChange()
        self._prepared = prepared
        self._image = QImage()
        self._frame = -1
        self.set_frame(0, full=True)

    def set_tracks(self, tracks: dict[int, NDArray[np.float64]], *,
                   color_for: Callable[[int], QColor], thickness: int,
                   show_markers: bool, marker_size: int) -> None:
        """Synchronous convenience API for small drawings and standalone callers."""
        prepared = prepare_paths(tracks, color_for=color_for, thickness=thickness,
                                 show_markers=show_markers, marker_size=marker_size)
        assert prepared is not None
        self.set_prepared(prepared)

    def set_frame(self, frame: int, *, full: bool) -> None:
        prepared = self._prepared
        if prepared is None:
            return
        self._image = prepared.full_image if full else prepared.image(frame)
        self._frame = frame
        self._full = full
        self.update()

    def getData(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        tracks = self._prepared.tracks if self._prepared is not None else {}
        x_values, y_values = [], []
        for points in tracks.values():
            visible = points if self._full else points[points[:, 0] <= self._frame]
            if len(visible):
                x_values.extend((visible[:, 1], np.asarray([np.nan])))
                y_values.extend((visible[:, 2], np.asarray([np.nan])))
        return (np.concatenate(x_values)[:-1], np.concatenate(y_values)[:-1]) if x_values else (
            np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64))

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, /,
              widget: QWidget | None = None) -> None:
        del option, widget
        if self._prepared is not None:
            painter.drawImage(self._prepared.bounds.topLeft(), self._image)

    def boundingRect(self) -> QRectF:
        return self._prepared.bounds if self._prepared is not None else QRectF()
