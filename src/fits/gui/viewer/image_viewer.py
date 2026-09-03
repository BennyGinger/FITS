from __future__ import annotations

import colorsys
from collections.abc import Callable
from typing import Any, Literal, cast

import numpy as np
import pyqtgraph as pg
from numpy.typing import NDArray
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog, QPushButton, QVBoxLayout, QWidget

from fits_io.metadata.imageJ_meta import COLOR_MAP, LABEL_TO_COLOR


DrawingMode = Literal["replace", "edit"]
DrawingTool = Literal["freehand", "line", "circle", "square", "triangle"]
DrawingOperation = Literal["add", "erase"]


class ControlledViewBox(pg.ViewBox):
    """Allow image navigation only while the Control key is held."""

    def mouseDragEvent(self, ev: Any, axis: int | None = None) -> None:
        if not ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            ev.ignore()
            return
        super().mouseDragEvent(ev, axis=axis)

    def wheelEvent(self, ev: Any, axis: int | None = None) -> None:
        if not ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            ev.ignore()
            return
        super().wheelEvent(ev, axis=axis)


class MaskDrawingItem(pg.ImageItem):
    """Transparent item that reports left-add and right-erase gestures."""

    def __init__(self) -> None:
        super().__init__(axisOrder="row-major")
        self.on_started: Callable[[float, float, DrawingOperation], None] | None = None
        self.on_moved: Callable[[float, float], None] | None = None
        self.on_finished: Callable[[float, float], None] | None = None
        self.setZValue(100)
        self.setAcceptedMouseButtons(cast(Qt.MouseButton, Qt.MouseButton.NoButton))

    def set_drawing_enabled(self, enabled: bool) -> None:
        buttons = ((Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
                   if enabled else Qt.MouseButton.NoButton)
        self.setAcceptedMouseButtons(cast(Qt.MouseButton, buttons))

    def mouseDragEvent(self, ev: Any) -> None:
        if (ev.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton)
                or ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            ev.ignore()
            return
        ev.accept()
        position = ev.pos()
        if ev.isStart() and self.on_started is not None:
            operation: DrawingOperation = (
                "erase" if ev.button() == Qt.MouseButton.RightButton else "add")
            self.on_started(position.x(), position.y(), operation)
        elif ev.isFinish() and self.on_finished is not None:
            self.on_finished(position.x(), position.y())
        elif self.on_moved is not None:
            self.on_moved(position.x(), position.y())

    def mouseClickEvent(self, ev: Any) -> None:
        if (ev.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton)
                or ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            ev.ignore()
            return
        ev.accept()
        position = ev.pos()
        if self.on_started is not None:
            operation: DrawingOperation = (
                "erase" if ev.button() == Qt.MouseButton.RightButton else "add")
            self.on_started(position.x(), position.y(), operation)
        if self.on_finished is not None:
            self.on_finished(position.x(), position.y())


class FitsImageViewer(QWidget):
    """
    Display a 2D image with a labelled-mask overlay.
    """

    drawing_finished = Signal(object)
    drawing_changed = Signal()
    drawing_started = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.canvas = pg.GraphicsLayoutWidget()
        self.view_box = ControlledViewBox()
        self.canvas.addItem(self.view_box)
        self.view_box.setAspectLocked(True)
        self.view_box.invertY(True)
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.mask_item = pg.ImageItem(axisOrder="row-major")
        self.drawing_item = MaskDrawingItem()
        self.view_box.addItem(self.image_item)
        self.view_box.addItem(self.mask_item)
        self.view_box.addItem(self.drawing_item)
        layout.addWidget(self.canvas)

        self.histogram = pg.HistogramLUTWidget(
            orientation="horizontal",
            gradientPosition="bottom",)
        self.histogram.setImageItem(self.image_item)
        self._has_image = False
        self._mask_opacity = 0.45
        self._mask_visible = True
        self._mask_array: NDArray[Any] | None = None
        self._mask_color: tuple[int, int, int] | None = None
        self._drawing_active = False
        self._lut_color = ""
        self._channel_label = ""
        self._coloured_lut = True
        self._connected_gradient_markers: set[object] = set()
        self._drawing_mask: NDArray[np.uint8] | None = None
        self._gesture_base: NDArray[np.uint8] | None = None
        self._drawing_start: tuple[int, int] | None = None
        self._drawing_last: tuple[int, int] | None = None
        self._drawing_points: list[tuple[int, int]] = []
        self._last_drawing_selection: NDArray[np.bool_] | None = None
        self._drawing_history: list[NDArray[np.uint8]] = []
        self._drawing_mode: DrawingMode = "replace"
        self._drawing_tool: DrawingTool = "freehand"
        self._drawing_operation: DrawingOperation = "add"
        self._brush_size = 5
        self.histogram.item.gradient.sigTicksChanged.connect(
            self._connect_gradient_markers)
        self.drawing_item.on_started = self._start_drawing
        self.drawing_item.on_moved = self._continue_drawing
        self.drawing_item.on_finished = self._finish_drawing
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

    def set_image(self, image: NDArray[Any]) -> None:
        """
        Display a 2D image and preserve manually selected LUT levels.
        """
        array = np.asarray(image)
        if array.ndim != 2:
            raise ValueError(f"The image viewer requires a 2D array; got shape {array.shape}.")
        self.image_item.setImage(array, autoLevels=not self._has_image)
        self.drawing_item.setImage(
            np.zeros((*array.shape, 4), dtype=np.uint8), autoLevels=False)
        self._has_image = True
        self.view_box.autoRange()

    @property
    def drawing_mask(self) -> NDArray[np.uint8]:
        """Return a copy of the current drawing canvas."""
        if self._drawing_mask is None:
            raise RuntimeError("No drawing mask is loaded.")
        return self._drawing_mask.copy()

    def set_drawing_enabled(self, enabled: bool) -> None:
        """Enable or disable drawing gestures over the image."""
        self.drawing_item.set_drawing_enabled(enabled)

    def set_drawing_options(self,
                            mode: DrawingMode,
                            tool: DrawingTool,
                            operation: DrawingOperation,
                            brush_size: int,
                            ) -> None:
        """Configure how subsequent mouse gestures modify the working mask."""
        self._drawing_mode = mode
        self._drawing_tool = tool
        self._drawing_operation = operation
        self._brush_size = max(1, int(brush_size))

    def set_drawing_mask(self, mask: NDArray[Any]) -> None:
        """Replace the working drawing canvas and display it as the mask overlay."""
        array = np.asarray(mask)
        if array.ndim != 2:
            raise ValueError(f"The drawing mask must be 2D; got shape {array.shape}.")
        self._drawing_mask = (array != 0).astype(np.uint8)
        self._drawing_history.clear()
        self.set_mask(self._drawing_mask)

    @property
    def can_undo_drawing(self) -> bool:
        """Return whether a previous drawing canvas is available."""
        return bool(self._drawing_history)

    @property
    def last_drawing_selection(self) -> NDArray[np.bool_] | None:
        """Return the pixels touched by the most recently completed gesture."""
        return (None if self._last_drawing_selection is None
                else self._last_drawing_selection.copy())

    @property
    def last_drawing_operation(self) -> DrawingOperation:
        return self._drawing_operation

    def undo_drawing(self) -> NDArray[np.uint8] | None:
        """Restore and return the canvas from before the latest gesture."""
        if not self._drawing_history:
            return None
        self._drawing_mask = self._drawing_history.pop()
        self.set_mask(self._drawing_mask)
        return self.drawing_mask

    def _remember_drawing(self) -> None:
        if self._drawing_mask is None:
            return
        self._drawing_history.append(self._drawing_mask.copy())
        del self._drawing_history[:-50]

    def clear_drawing_mask(self) -> None:
        """Clear the working drawing canvas without emitting a commit signal."""
        if self._drawing_mask is None:
            return
        self._remember_drawing()
        self._drawing_mask.fill(0)
        mask = self._drawing_mask
        self.set_mask(mask)

    def _start_drawing(self, x_position: float, y_position: float,
                       operation: DrawingOperation = "add") -> None:
        if self._drawing_mask is None:
            return
        self.drawing_started.emit()
        self._drawing_operation = operation
        self._drawing_active = True
        self.mask_item.setOpacity(max(self._mask_opacity, 0.8))
        self._remember_drawing()
        point = self._drawing_point(x_position, y_position)
        self._gesture_base = (np.zeros_like(self._drawing_mask)
                              if self._drawing_mode == "replace"
                              else self._drawing_mask.copy())
        self._drawing_mask = self._gesture_base.copy()
        self._drawing_start = point
        self._drawing_last = point
        self._drawing_points = [point]
        self._last_drawing_selection = None
        self._apply_drawing(point)

    def _continue_drawing(self, x_position: float, y_position: float) -> None:
        if self._drawing_start is None or self._gesture_base is None:
            return
        point = self._drawing_point(x_position, y_position)
        self._apply_drawing(point)

    def _finish_drawing(self, x_position: float, y_position: float) -> None:
        if self._drawing_start is None or self._gesture_base is None:
            return
        point = self._drawing_point(x_position, y_position)
        self._apply_drawing(point)
        self._drawing_start = None
        self._drawing_last = None
        self._drawing_points = []
        self._gesture_base = None
        self._drawing_active = False
        self.mask_item.setOpacity(self._mask_opacity)
        self.drawing_changed.emit()
        self.drawing_finished.emit(self.drawing_mask)

    def _apply_drawing(self, point: tuple[int, int]) -> None:
        if (self._drawing_mask is None
                or self._gesture_base is None
                or self._drawing_start is None):
            return
        if self._drawing_tool == "freehand":
            if point != self._drawing_points[-1]:
                self._drawing_points.append(point)
            self._drawing_mask = self._gesture_base.copy()
            selected = self._freehand_polygon_selection(self._drawing_points)
            self._drawing_last = point
        elif self._drawing_tool == "line":
            self._drawing_mask = self._gesture_base.copy()
            selected = self._line_selection(self._drawing_start, point)
        else:
            self._drawing_mask = self._gesture_base.copy()
            selected = self._shape_selection(self._drawing_start, point)
        self._last_drawing_selection = selected.copy()
        self._drawing_mask[selected] = 0 if self._drawing_operation == "erase" else 1
        self.set_mask(self._drawing_mask)

    def _drawing_point(self, x_position: float, y_position: float) -> tuple[int, int]:
        if self._drawing_mask is None:
            return 0, 0
        row = min(max(int(round(y_position)), 0), self._drawing_mask.shape[0] - 1)
        column = min(max(int(round(x_position)), 0), self._drawing_mask.shape[1] - 1)
        return row, column

    def _freehand_polygon_selection(self,
                                    points: list[tuple[int, int]],
                                    ) -> NDArray[np.bool_]:
        """Fill the polygon enclosed by the live free-hand cursor path."""
        if self._drawing_mask is None:
            raise RuntimeError("No drawing mask is loaded.")
        selected = np.zeros(self._drawing_mask.shape, dtype=bool)
        for start, end in zip(points[:-1], points[1:], strict=True):
            selected |= self._line_selection(start, end)
        if len(points) < 3:
            return selected | self._line_selection(points[0], points[-1])

        grid_rows, grid_columns = np.indices(selected.shape, dtype=float)
        vertices = np.asarray(points, dtype=float)
        previous = vertices[-1]
        inside = np.zeros(selected.shape, dtype=bool)
        for current in vertices:
            row_crossing = (current[0] > grid_rows) != (previous[0] > grid_rows)
            denominator = previous[0] - current[0]
            if denominator != 0:
                boundary = ((previous[1] - current[1])
                            * (grid_rows - current[0]) / denominator
                            + current[1])
                inside ^= row_crossing & (grid_columns < boundary)
            previous = current
        selected |= inside
        selected |= self._line_selection(points[-1], points[0])
        return selected

    def _line_selection(self,
                        start: tuple[int, int],
                        end: tuple[int, int],
                        ) -> NDArray[np.bool_]:
        if self._drawing_mask is None:
            raise RuntimeError("No drawing mask is loaded.")
        selected = np.zeros(self._drawing_mask.shape, dtype=bool)
        steps = max(abs(end[0] - start[0]), abs(end[1] - start[1])) + 1
        rows = np.rint(np.linspace(start[0], end[0], steps)).astype(int)
        columns = np.rint(np.linspace(start[1], end[1], steps)).astype(int)
        radius = max((self._brush_size - 1) / 2, 0.5)
        grid_rows, grid_columns = np.ogrid[:selected.shape[0], :selected.shape[1]]
        for row, column in zip(rows, columns, strict=True):
            selected |= ((grid_rows - row) ** 2 + (grid_columns - column) ** 2
                         <= radius ** 2)
        return selected

    def _shape_selection(self,
                         start: tuple[int, int],
                         end: tuple[int, int],
                         ) -> NDArray[np.bool_]:
        if self._drawing_mask is None:
            raise RuntimeError("No drawing mask is loaded.")
        rows, columns = np.ogrid[:self._drawing_mask.shape[0], :self._drawing_mask.shape[1]]
        if self._drawing_tool == "circle":
            radius_squared = (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2
            return ((rows - start[0]) ** 2 + (columns - start[1]) ** 2
                    <= radius_squared)
        if self._drawing_tool == "square":
            side = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
            end_row = start[0] + side * (1 if end[0] >= start[0] else -1)
            end_column = start[1] + side * (1 if end[1] >= start[1] else -1)
            row_min, row_max = sorted((start[0], end_row))
            column_min, column_max = sorted((start[1], end_column))
            return ((rows >= row_min) & (rows <= row_max)
                    & (columns >= column_min) & (columns <= column_max))
        return self._triangle_selection(start, end)

    def _triangle_selection(self,
                            apex: tuple[int, int],
                            end: tuple[int, int],
                            ) -> NDArray[np.bool_]:
        if self._drawing_mask is None:
            raise RuntimeError("No drawing mask is loaded.")
        half_width = max(abs(end[1] - apex[1]), 1)
        first_base = (end[0], apex[1] - half_width)
        second_base = (end[0], apex[1] + half_width)
        rows, columns = np.indices(self._drawing_mask.shape)
        denominator = ((first_base[1] - second_base[1]) * (apex[0] - second_base[0])
                       + (second_base[0] - first_base[0]) * (apex[1] - second_base[1]))
        if denominator == 0:
            selected = np.zeros(self._drawing_mask.shape, dtype=bool)
            selected[apex] = True
            return selected
        first_weight = (((first_base[1] - second_base[1]) * (rows - second_base[0])
                        + (second_base[0] - first_base[0]) * (columns - second_base[1]))
                        / denominator)
        second_weight = (((second_base[1] - apex[1]) * (rows - second_base[0])
                         + (apex[0] - second_base[0]) * (columns - second_base[1]))
                         / denominator)
        third_weight = 1 - first_weight - second_weight
        return (first_weight >= 0) & (second_weight >= 0) & (third_weight >= 0)

    def set_mask(self, mask: NDArray[Any]) -> None:
        """
        Display a labelled 2D mask as a transparent colour overlay.
        """
        array = np.asarray(mask)
        if array.ndim != 2:
            raise ValueError(f"The mask viewer requires a 2D array; got shape {array.shape}.")
        self._mask_array = array.copy()
        self.mask_item.setImage(
            self._colour_mask(array, self._mask_color), autoLevels=False)
        opacity = max(self._mask_opacity, 0.8) if self._drawing_active else self._mask_opacity
        self.mask_item.setOpacity(opacity)
        self.mask_item.setVisible(self._mask_visible)

    def clear_mask(self) -> None:
        self._mask_array = None
        self.mask_item.clear()

    def set_mask_color(self, color: QColor | None) -> None:
        """Use one solid mask colour, or the label colour map when ``None``."""
        self._mask_color = ((color.red(), color.green(), color.blue())
                            if color is not None
                            else None)
        if self._mask_array is not None:
            self.mask_item.setImage(
                self._colour_mask(self._mask_array, self._mask_color),
                autoLevels=False)

    def set_mask_visible(self, visible: bool) -> None:
        self._mask_visible = visible
        self.mask_item.setVisible(visible)

    def set_mask_opacity(self, opacity: float) -> None:
        self._mask_opacity = min(max(opacity, 0.0), 1.0)
        displayed = max(self._mask_opacity, 0.8) if self._drawing_active else self._mask_opacity
        self.mask_item.setOpacity(displayed)

    @staticmethod
    def _colour_mask(mask: NDArray[Any],
                     solid_color: tuple[int, int, int] | None = None,
                     ) -> NDArray[np.uint8]:
        labels = np.asarray(mask)
        rgba = np.zeros((*labels.shape, 4), dtype=np.uint8)
        if solid_color is not None:
            selected = labels != 0
            rgba[selected, :3] = solid_color
            rgba[selected, 3] = 255
            return rgba
        for label in np.unique(labels):
            if label == 0:
                continue
            hue = (int(label) * 0.61803398875) % 1.0
            red, green, blue = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
            selected = labels == label
            rgba[selected, :3] = np.asarray([red, green, blue]) * 255
            rgba[selected, 3] = 255
        return rgba
