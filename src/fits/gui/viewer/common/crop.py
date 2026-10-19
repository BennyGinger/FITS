"""Shared manual rectangle, sizing and crop-preview controls."""

from math import ceil, floor
from typing import cast

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPen
from PySide6.QtWidgets import QApplication, QCheckBox, QColorDialog, QGraphicsRectItem, QGraphicsView
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fits.gui.settings.wheel_widgets import FocusWheelSpinBox
from fits.gui.viewer.common.image_viewer import FitsImageViewer
from fits.interaction.crop import CropBounds


class CropPanel(QWidget):
    changed = Signal()
    crop_requested = Signal()
    cell_clicked = Signal(object)
    rectangle_selected = Signal(object)

    def __init__(self, *, automatic: bool = True) -> None:
        """Build rectangle controls, optionally including automatic tracking selection."""
        super().__init__()
        self._automatic = automatic
        self._active = True
        self.bounds: CropBounds | None = None
        self._shape = (0, 0)
        self._viewer: FitsImageViewer | None = None
        self._canvas: QGraphicsView | None = None
        self._viewport: QWidget | None = None
        self._gesture = ""
        self._start = QPointF()
        self._start_pixel = QPoint()
        self._original: CropBounds | None = None
        self._busy = False
        self._color = QColor("yellow")
        self.rectangle = QGraphicsRectItem()
        self.rectangle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.rectangle.setZValue(80)
        self.rectangle.hide()
        self.selection_rectangle = QGraphicsRectItem()
        self.selection_rectangle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.selection_rectangle.setZValue(81)
        self.selection_rectangle.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox("Enable crop")
        self.enabled.setToolTip(
            "Draw a rectangle to select cells, then adjust it or fit it with Crop. "
            "Saving uses this crop even in the home view." if automatic else
            "Enable drawing and fit registration using only this rectangle. "
            "Transforms still apply to the full image. Disable to use the full image again.")
        layout.addWidget(self.enabled)
        sizes = QHBoxLayout()
        self.width_input = FocusWheelSpinBox()
        self.height_input = FocusWheelSpinBox()
        for name, field in (("Width", self.width_input), ("Height", self.height_input)):
            field.setRange(1, 1)
            field.setSuffix(" px")
            field.setKeyboardTracking(False)
            sizes.addWidget(QLabel(name))
            sizes.addWidget(field, 1)
            field.valueChanged.connect(self._resize)
        layout.addLayout(sizes)
        buttons = QHBoxLayout()
        self.color_button = QPushButton("Rectangle colour")
        self.color_button.setToolTip("Display colour only; the rectangle is excluded from the export.")
        self._update_color()
        self.crop_button = QPushButton("Crop") if automatic else None
        if self.crop_button is not None:
            self.crop_button.setToolTip("Fit a rectangle around all selected cells across time, plus 5% on each side.")
        self.preview_button = QPushButton("Preview")
        self.preview_button.setCheckable(True)
        self.preview_button.setToolTip("Zoom to the rectangle. Turn off or press Home to see the full image.")
        for button in (self.color_button, self.crop_button, self.preview_button):
            if button is not None:
                buttons.addWidget(button)
        layout.addLayout(buttons)
        self.enabled.toggled.connect(self._toggle)
        if self.crop_button is not None:
            self.crop_button.clicked.connect(self.crop_requested)
        self.preview_button.toggled.connect(self._preview)
        self.color_button.clicked.connect(self._choose_color)
        self._update_controls()

    def bind(self, viewer: FitsImageViewer) -> None:
        """Attach rectangle graphics and mouse handling to a viewer."""
        self._viewer = viewer
        viewer.view_box.addItem(self.rectangle, ignoreBounds=True)
        viewer.view_box.addItem(self.selection_rectangle, ignoreBounds=True)
        self._canvas = cast(QGraphicsView, viewer.canvas)
        self._viewport = self._canvas.viewport()
        assert self._viewport is not None
        self._viewport.installEventFilter(self)
        self._viewport.setMouseTracking(True)
        viewer.home_button.clicked.connect(lambda: self.preview_button.setChecked(False))

    def reset(self, shape: tuple[int, int] = (0, 0)) -> None:
        """Clear the rectangle and disable drawing for a newly loaded image."""
        self.enabled.setChecked(False)
        self.bounds = None
        self._gesture = ""
        self._shape = shape
        self.rectangle.hide()
        self.selection_rectangle.hide()
        self.width_input.setMaximum(max(1, shape[1]))
        self.height_input.setMaximum(max(1, shape[0]))
        self._update_controls()

    def set_busy(self, busy: bool) -> None:
        """Suspend editing while the owner is computing a preview."""
        self._busy = busy
        self._update_controls()

    def _update_controls(self) -> None:
        """Enable only controls appropriate for the current image and rectangle."""
        available = all(self._shape) and not self._busy
        active = available and self.enabled.isChecked()
        self.enabled.setEnabled(available)
        if self.crop_button is not None:
            self.crop_button.setEnabled(active)
        self.color_button.setEnabled(active)
        self.preview_button.setEnabled(active and self.bounds is not None)
        self.width_input.setEnabled(active and self.bounds is not None)
        self.height_input.setEnabled(active and self.bounds is not None)

    def set_bounds(self, bounds: CropBounds) -> None:
        """Set a full-image rectangle and synchronize the numeric dimensions."""
        x0, y0, x1, y1 = bounds
        height, width = self._shape
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError("Crop rectangle must lie inside the image.")
        self.bounds = bounds
        self.rectangle.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        for field, value in ((self.width_input, x1 - x0), (self.height_input, y1 - y0)):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self.rectangle.setVisible(self._active and self.enabled.isChecked())
        self._update_controls()
        if self.preview_button.isChecked() and not self._gesture:
            self._preview(True)
        self.changed.emit()

    def set_active(self, active: bool) -> None:
        """Allow only the selected tab's rectangle to interact with the shared viewer."""
        if self._active == active:
            return
        if not active and self._viewer is not None:
            self._viewer.reset_view()
        self._active = active
        self._gesture = ""
        self.selection_rectangle.hide()
        self.rectangle.setVisible(active and self.enabled.isChecked() and self.bounds is not None)
        if active and self.preview_button.isChecked():
            self._preview(True)

    def _toggle(self, active: bool) -> None:
        """Toggle drawing and return to the full image when disabled."""
        self._gesture = ""
        self.selection_rectangle.hide()
        self.rectangle.setVisible(self._active and active and self.bounds is not None)
        if not active:
            self.preview_button.setChecked(False)
            if self._active and self._viewer is not None and not self._automatic:
                self._viewer.reset_view()
            if self._viewport is not None:
                self._viewport.unsetCursor()
        self._update_controls()
        self.changed.emit()

    def _preview(self, active: bool) -> None:
        """Zoom to the rectangle without changing image pixels or crop eligibility."""
        if self._viewer is None or not self._active:
            return
        if active and self.bounds is not None:
            self._viewer.view_box.setRange(self.rectangle.rect(), padding=0)
        elif not active:
            self._viewer.reset_view()

    def _resize(self) -> None:
        """Resize about the rectangle centre while keeping it inside the image."""
        if self.bounds is None:
            return
        x0, y0, x1, y1 = self.bounds
        width, height = self.width_input.value(), self.height_input.value()
        left = min(max(0, round((x0 + x1 - width) / 2)), self._shape[1] - width)
        top = min(max(0, round((y0 + y1 - height) / 2)), self._shape[0] - height)
        self.set_bounds((left, top, left + width, top + height))

    def _choose_color(self) -> None:
        """Choose the display colour of the rectangle."""
        color = QColorDialog.getColor(self._color, self, "Crop rectangle colour")
        if color.isValid():
            self._color = color
            self._update_color()

    def _update_color(self) -> None:
        """Apply the selected colour to rectangle graphics and the colour button."""
        pen = QPen(self._color)
        pen.setWidth(2)
        pen.setCosmetic(True)
        self.rectangle.setPen(pen)
        self.selection_rectangle.setPen(pen)
        self.color_button.setStyleSheet(f"background-color: {self._color.name()}; color: black;")

    def _hit(self, position: QPointF) -> str:
        """Identify a draw, move or resize gesture at the given image position."""
        if self.bounds is None or self._viewer is None:
            return "draw"
        x0, y0, x1, y1 = self.bounds
        pixel_x, pixel_y = self._viewer.view_box.viewPixelSize()
        tolerance_x, tolerance_y = abs(pixel_x) * 6, abs(pixel_y) * 6
        x, y = position.x(), position.y()
        if not (x0 - tolerance_x <= x <= x1 + tolerance_x
                and y0 - tolerance_y <= y <= y1 + tolerance_y):
            return "draw"
        horizontal = "left" if abs(x - x0) <= tolerance_x else "right" if abs(x - x1) <= tolerance_x else ""
        vertical = "top" if abs(y - y0) <= tolerance_y else "bottom" if abs(y - y1) <= tolerance_y else ""
        return "_".join(part for part in (horizontal, vertical) if part) or "move"

    def _drag_to(self, point: QPointF) -> None:
        """Update the rectangle for the current draw, move or resize gesture."""
        height, width = self._shape
        x, y = min(max(point.x(), 0), width), min(max(point.y(), 0), height)
        if self._gesture == "draw":
            left, top, right, bottom = self._draw_bounds(point)
        elif self._original is not None:
            left, top, right, bottom = self._original
            if self._gesture == "move":
                dx = min(max(round(x - self._start.x()), -left), width - right)
                dy = min(max(round(y - self._start.y()), -top), height - bottom)
                left, right, top, bottom = left + dx, right + dx, top + dy, bottom + dy
            else:
                if "left" in self._gesture:
                    left = min(round(x), right - 1)
                if "right" in self._gesture:
                    right = max(round(x), left + 1)
                if "top" in self._gesture:
                    top = min(round(y), bottom - 1)
                if "bottom" in self._gesture:
                    bottom = max(round(y), top + 1)
        else:
            return
        self.set_bounds((left, top, right, bottom))

    def _draw_bounds(self, point: QPointF) -> CropBounds:
        """Convert a drag into clipped integer bounds with exclusive outer edges."""
        height, width = self._shape
        x = min(max(point.x(), 0), width)
        y = min(max(point.y(), 0), height)
        left = min(max(0, floor(min(self._start.x(), x))), width - 1)
        top = min(max(0, floor(min(self._start.y(), y))), height - 1)
        right = min(width, max(left + 1, ceil(max(self._start.x(), x))))
        bottom = min(height, max(top + 1, ceil(max(self._start.y(), y))))
        return left, top, right, bottom

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Handle rectangle gestures only while the appropriate tool is active."""
        if (self._viewer is None or self._canvas is None or self._viewport is None
                or not self._active or not all(self._shape) or self._busy
                or self._viewer._loading_visible or not isinstance(event, QMouseEvent)):
            return False
        crop_active = self.enabled.isChecked()
        control = self._automatic and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        scene = self._canvas.mapToScene(event.position().toPoint())
        point = self._viewer.view_box.mapSceneToView(scene)
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if not (crop_active or control) or not self._viewer.view_box.sceneBoundingRect().contains(scene.x(), scene.y()):
                return False
            self._start, self._original = point, self.bounds
            self._start_pixel = event.position().toPoint()
            self._gesture = "select_pending" if control else self._hit(point)
            if self._gesture == "draw":
                self._gesture = "draw_pending"
            return True
        if event.type() == QEvent.Type.MouseMove:
            if self._gesture:
                if self._gesture in ("select_pending", "draw_pending"):
                    if (event.position().toPoint() - self._start_pixel).manhattanLength() < QApplication.startDragDistance():
                        return True
                    self._gesture = "select" if self._gesture == "select_pending" else "draw"
                if self._gesture == "select":
                    bounds = self._draw_bounds(point)
                    if crop_active:
                        self.set_bounds(bounds)
                    else:
                        x0, y0, x1, y1 = bounds
                        self.selection_rectangle.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                        self.selection_rectangle.show()
                else:
                    self._drag_to(point)
                return True
            if not crop_active:
                return False
            cursors = {"move": Qt.CursorShape.SizeAllCursor,
                       "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
                       "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
                       "left_top": Qt.CursorShape.SizeFDiagCursor, "right_bottom": Qt.CursorShape.SizeFDiagCursor,
                       "left_bottom": Qt.CursorShape.SizeBDiagCursor, "right_top": Qt.CursorShape.SizeBDiagCursor}
            self._viewport.setCursor(cursors.get(self._hit(point), Qt.CursorShape.CrossCursor))
        if (event.type() == QEvent.Type.MouseButtonRelease and self._gesture
                and event.button() == Qt.MouseButton.LeftButton):
            gesture = self._gesture
            if gesture == "select_pending":
                self.cell_clicked.emit(self._start)
            elif gesture != "draw_pending":
                if gesture == "select":
                    bounds = self._draw_bounds(point)
                    if crop_active:
                        self.set_bounds(bounds)
                    else:
                        self.selection_rectangle.hide()
                else:
                    self._drag_to(point)
                    bounds = self.bounds
                if bounds is not None:
                    self.rectangle_selected.emit(bounds)
            self._gesture = ""
            if crop_active and self.preview_button.isChecked():
                self._preview(True)
            return True
        return False
