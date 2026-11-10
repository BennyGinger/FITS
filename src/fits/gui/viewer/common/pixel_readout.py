"""Compact hover intensities sampled from the current in-memory image planes."""

from math import floor
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from numpy.typing import NDArray
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QWidget


class PixelReadout(QGroupBox):
    """
    Show one intensity or two intensities with shortened channel tags.
    """

    def __init__(self, image_item: pg.ImageItem, canvas: pg.GraphicsLayoutWidget) -> None:
        """
        Observe mouse motion without reading files or processing image planes.
        """
        super().__init__(cast(QWidget, canvas))
        value_font = QFont(self.font())
        title_font = QFont(value_font)
        title_font.setItalic(True)
        title_font.setPointSize(8)
        self.setFont(title_font)
        self.setTitle("Intensities")
        self.setStyleSheet("QGroupBox { border: 1px solid #777; border-radius: 3px; margin-top: 10px; } "
                          "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; "
                          "padding: 0 3px; font-style: italic; }")
        self._measurements: tuple[tuple[str, float], ...] | None = None
        self._image_item = image_item
        self._planes: tuple[tuple[str, NDArray[Any]], ...] = ()
        self._position: QPointF | None = None
        self._pixel: tuple[int, int] | None = None
        self.single_value = QLabel("—")
        self.single_tag = QLabel()
        self.values = (QLabel("—"), QLabel("—"))
        self.tags = (QLabel(), QLabel())
        layout = QGridLayout(self)
        layout.setContentsMargins(4, 10, 4, 3)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.single_value, 0, 0, 1, 2)
        layout.addWidget(self.single_tag, 1, 0, 1, 2)
        for index in range(2):
            layout.setColumnStretch(index, 1)
            layout.addWidget(self.values[index], 0, index)
            layout.addWidget(self.tags[index], 1, index)
        for label in (self.single_value, self.single_tag, *self.values, *self.tags):
            label.setFont(value_font)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumWidth(0)
        metrics = QFontMetrics(value_font)
        self.setFixedWidth(2 * metrics.horizontalAdvance("-65535.0") + 16)
        self.setMinimumHeight(2 * metrics.height() + 25)
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
        self.single_tag.setVisible(not composite)
        self.single_tag.setText("")
        tag_width = (self.width() - 8) // 2
        for index in range(2):
            self.values[index].setVisible(composite)
            self.tags[index].setVisible(composite)
            name = planes[index][0] if composite else ""
            self.tags[index].setText(self.tags[index].fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, tag_width))
            self.tags[index].setToolTip(name)
        self._pixel = None
        if self._measurements is not None:
            self.set_measurements(self._measurements)
        else:
            self._update_values()

    def set_measurements(self, values: tuple[tuple[str, float], ...] | None) -> None:
        """
        Replace hover values with area means until the selection is cleared.
        """
        self._measurements = values
        if values is None:
            self.set_planes(self._planes)
            return
        composite = len(values) == 2
        self.single_value.setVisible(not composite)
        self.single_tag.setVisible(not composite)
        self.single_tag.setText("Mean" if not composite else "")
        for index in range(2):
            self.values[index].setVisible(composite)
            self.tags[index].setVisible(composite)
        for index, (name, value) in enumerate(values):
            label = self.values[index] if composite else self.single_value
            label.setText(_format_intensity(value))
            label.setToolTip(f"{name}: {value}")
            if composite:
                self.tags[index].setText(self.tags[index].fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight,
                                                                                 (self.width() - 16) // 2))
                self.tags[index].setToolTip(name)

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
        if self._measurements is not None:
            return
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
