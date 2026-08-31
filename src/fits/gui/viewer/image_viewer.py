from __future__ import annotations

import colorsys
from typing import Any

import numpy as np
import pyqtgraph as pg
from numpy.typing import NDArray
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QColorDialog, QDialog, QPushButton, QVBoxLayout, QWidget

from fits_io.metadata.imageJ_meta import COLOR_MAP, LABEL_TO_COLOR


class FitsImageViewer(QWidget):
    """
    Display a 2D image with a labelled-mask overlay.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.canvas = pg.GraphicsLayoutWidget()
        self.view_box = self.canvas.addViewBox()
        self.view_box.setAspectLocked(True)
        self.view_box.invertY(True)
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.mask_item = pg.ImageItem(axisOrder="row-major")
        self.view_box.addItem(self.image_item)
        self.view_box.addItem(self.mask_item)
        layout.addWidget(self.canvas)

        self.histogram = pg.HistogramLUTWidget(
            orientation="horizontal",
            gradientPosition="bottom",)
        self.histogram.setImageItem(self.image_item)
        self._has_image = False
        self._mask_opacity = 0.45
        self._lut_color = ""
        self._channel_label = ""
        self._coloured_lut = True
        self._connected_gradient_markers: set[object] = set()
        self.histogram.item.gradient.sigTicksChanged.connect(
            self._connect_gradient_markers)
        self.set_channel_lut("")

    @property
    def lut_color(self) -> str:
        return self._lut_color

    def set_channel_lut(self, channel_label: str) -> None:
        """
        Colour the image from its FITS channel label or use grayscale.
        """
        color = (LABEL_TO_COLOR.get(channel_label.strip().lower(), "gray")
                 if self._coloured_lut
                 else "gray")
        if channel_label == self._channel_label and color == self._lut_color:
            return
        self._channel_label = channel_label
        red, green, blue = COLOR_MAP[color]
        color_map = pg.ColorMap(
            [0.0, 1.0],
            [(0, 0, 0, 255),
             (red * 255, green * 255, blue * 255, 255)],)
        self.histogram.item.gradient.setColorMap(color_map)
        self._lut_color = color

    def set_coloured_lut(self, coloured: bool) -> None:
        self._coloured_lut = coloured
        self.set_channel_lut(self._channel_label)

    def auto_scale(self) -> None:
        """
        Set robust display levels from the first and ninety-ninth percentiles.
        """
        image = self.image_item.image
        if image is None:
            return
        minimum, maximum = np.nanpercentile(image, (1.0, 99.0))
        self._set_levels(float(minimum), float(maximum))

    def full_range(self) -> None:
        """
        Reset display levels to the complete finite image range.
        """
        image = self.image_item.image
        if image is None:
            return
        self._set_levels(float(np.nanmin(image)), float(np.nanmax(image)))

    @property
    def display_levels(self) -> tuple[float, float]:
        minimum, maximum = self.histogram.getLevels()
        return float(minimum), float(maximum)

    def set_display_levels(self, levels: tuple[float, float]) -> None:
        self._set_levels(*levels)

    def _remove_gradient_marker(self, marker: Any) -> bool:
        if not marker.removeAllowed:
            return False
        self.histogram.item.gradient.removeTick(marker)
        return True

    def _connect_gradient_markers(self) -> None:
        gradient = self.histogram.item.gradient
        for marker in gradient.ticks:
            if marker in self._connected_gradient_markers:
                continue
            marker.sigClicked.disconnect(gradient.tickClicked)
            marker.sigClicked.connect(self._edit_gradient_marker)
            self._connected_gradient_markers.add(marker)

    def _edit_gradient_marker(self, marker: Any, event: Any) -> None:
        gradient = self.histogram.item.gradient
        if event.button() == Qt.MouseButton.RightButton:
            gradient.raiseTickContextMenu(marker, event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        dialog = QColorDialog(marker.color, self)
        dialog.setWindowTitle("Edit marker")
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if marker.removeAllowed:
            remove_button = QPushButton("Remove marker")
            remove_button.clicked.connect(
                lambda: self._remove_marker_from_dialog(marker, dialog))
            dialog_layout = dialog.layout()
            if dialog_layout is not None:
                dialog_layout.addWidget(remove_button)
        if dialog.exec() == QDialog.DialogCode.Accepted and marker in gradient.ticks:
            gradient.setTickColor(marker, dialog.selectedColor())

    def _remove_marker_from_dialog(self, marker: Any, dialog: QColorDialog) -> None:
        self._remove_gradient_marker(marker)
        dialog.reject()

    def _set_levels(self, minimum: float, maximum: float) -> None:
        if not np.isfinite(minimum) or not np.isfinite(maximum):
            return
        if minimum == maximum:
            maximum = minimum + 1.0
        self.histogram.setLevels(minimum, maximum)

    def set_image(self, image: NDArray[object]) -> None:
        """
        Display a 2D image and preserve manually selected LUT levels.
        """
        array = np.asarray(image)
        if array.ndim != 2:
            raise ValueError(f"The image viewer requires a 2D array; got shape {array.shape}.")
        self.image_item.setImage(array, autoLevels=not self._has_image)
        self._has_image = True
        self.view_box.autoRange()

    def set_mask(self, mask: NDArray[object]) -> None:
        """
        Display a labelled 2D mask as a transparent colour overlay.
        """
        array = np.asarray(mask)
        if array.ndim != 2:
            raise ValueError(f"The mask viewer requires a 2D array; got shape {array.shape}.")
        self.mask_item.setImage(self._colour_mask(array), autoLevels=False)
        self.mask_item.setOpacity(self._mask_opacity)
        self.mask_item.show()

    def clear_mask(self) -> None:
        self.mask_item.clear()

    def set_mask_visible(self, visible: bool) -> None:
        self.mask_item.setVisible(visible)

    def set_mask_opacity(self, opacity: float) -> None:
        self._mask_opacity = min(max(opacity, 0.0), 1.0)
        self.mask_item.setOpacity(self._mask_opacity)

    @staticmethod
    def _colour_mask(mask: NDArray[object]) -> NDArray[np.uint8]:
        labels = np.asarray(mask)
        rgba = np.zeros((*labels.shape, 4), dtype=np.uint8)
        for label in np.unique(labels):
            if label == 0:
                continue
            hue = (int(label) * 0.61803398875) % 1.0
            red, green, blue = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
            selected = labels == label
            rgba[selected, :3] = np.asarray([red, green, blue]) * 255
            rgba[selected, 3] = 255
        return rgba
