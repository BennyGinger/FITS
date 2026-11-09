"""Compact hover intensities sampled from the current in-memory image planes."""

from math import floor
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from numpy.typing import NDArray
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget


class PixelReadout(QWidget):
    """
    Show one intensity or two intensities with shortened channel tags.
    """

    def __init__(self, image_item: pg.ImageItem, canvas: pg.GraphicsLayoutWidget) -> None:
        """
        Observe mouse motion without reading files or processing image planes.
        """
        super().__init__(cast(QWidget, canvas))
        self._image_item = image_item
        self._planes: tuple[tuple[str, NDArray[Any]], ...] = ()
        self._position: QPointF | None = None
        self._pixel: tuple[int, int] | None = None
        self.single_value = QLabel("—")
        self.values = (QLabel("—"), QLabel("—"))
        self.tags = (QLabel(), QLabel())
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(0)
        layout.addWidget(self.single_value, 0, 0, 1, 2)
        for index in range(2):
            layout.setColumnStretch(index, 1)
            layout.addWidget(self.values[index], 0, index)
            layout.addWidget(self.tags[index], 1, index)
        for label in (self.single_value, *self.values, *self.tags):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumWidth(0)
        metrics = self.fontMetrics()
        self.setFixedWidth(2 * metrics.horizontalAdvance("-65535.0") + 16)
        self.setFixedHeight(2 * metrics.height())
        self._viewport = cast(QWidget, canvas.viewport())
        self._mouse_proxy = pg.SignalProxy(cast(Any, canvas.scene()).sigMouseMoved, rateLimit=30,
                                           delay=1 / 30, slot=self._mouse_moved,
                                           )
        self.set_planes(())

    def set_planes(self, planes: tuple[tuple[str, NDArray[Any]], ...]) -> None:
        """
        Retain source planes by reference and refresh even when the cursor is still.
        """
        self._planes = planes
        if not planes:
            self._position = None
        composite = len(planes) == 2
        self.single_value.setVisible(not composite)
        tag_width = (self.width() - 8) // 2
        for index in range(2):
            self.values[index].setVisible(composite)
            name = planes[index][0] if composite else ""
            self.tags[index].setText(self.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, tag_width))
            self.tags[index].setToolTip(name)
        self._pixel = None
        self._update_values()

    def _mouse_moved(self, events: tuple[QPointF]) -> None:
        """
        Sample at most thirty times per second and skip unchanged pixel positions.
        """
        if self._viewport.underMouse():
            self._position = events[0]
            self._update_values()
        else:
            self._position = None
            self._pixel = None

    def _update_values(self) -> None:
        """
        Read the hovered pixel from each contributing plane before LUT blending.
        """
        pixel = None
        if self._position is not None and self._planes:
            position = self._image_item.mapFromScene(cast(Any, self._position))
            pixel = (floor(position.y()), floor(position.x()))
        if pixel is not None and pixel == self._pixel:
            return
        self._pixel = pixel
        labels = self.values if len(self._planes) == 2 else (self.single_value,)
        for index, label in enumerate(labels):
            text, tooltip = "—", ""
            if pixel is not None:
                name, plane = self._planes[index]
                row, column = pixel
                if 0 <= row < plane.shape[0] and 0 <= column < plane.shape[1]:
                    value = plane[row, column].item()
                    text = _format_intensity(value)
                    tooltip = f"{name}: {value}" if name else str(value)
            label.setText(text)
            label.setToolTip(tooltip)


def _format_intensity(value: int | float) -> str:
    """
    Keep ordinary values readable and use compact notation for larger magnitudes.
    """
    text = f"{value:.1f}".removesuffix(".0")
    return text if len(text) <= 8 else f"{value:.2g}"
