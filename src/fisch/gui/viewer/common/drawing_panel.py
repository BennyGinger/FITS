"""Persistent image selections with native pyqtgraph move and resize handles."""

from math import hypot
from typing import Any, cast

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPolygonF
from PySide6.QtWidgets import QApplication, QColorDialog, QHBoxLayout, QPushButton, QWidget

from fisch.gui.settings.wheel_widgets import FocusWheelComboBox
from fisch.gui.viewer.common.area_selection import AreaSelection
from fisch.gui.viewer.common.image_viewer import FischImageViewer


class DrawingPanel(QWidget):
    """
    Draw one replaceable selection without changing image or mask data.
    """

    changed = Signal()
    finished = Signal()
    rectangle_selected = Signal(object)
    cell_clicked = Signal(object)

    def __init__(self) -> None:
        """
        Build shape and display-colour controls with rectangle selected by default.
        """
        super().__init__()
        self.shape_combo = FocusWheelComboBox()
        self.shape_combo.addItems(["Rectangle", "Ellipse", "Polygon"])
        self.color_button = QPushButton("Shape colour")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.shape_combo, 1)
        row.addWidget(self.color_button, 1)
        self._color = QColor("yellow")
        self._viewer: FischImageViewer | None = None
        self._roi: Any = None
        self._points: list[tuple[float, float]] = []
        self._start: QPointF | None = None
        self._start_screen = QPointF()
        self._dragged = False
        self._new_roi = False
        self._gesture = ""
        self._original: AreaSelection | None = None
        self._original_pos = (0.0, 0.0)
        self._control_start: QPointF | None = None
        self._kind = "Rectangle"
        self._shape = (0, 0)
        self._muted = False
        self.color_button.clicked.connect(self._choose_color)
        self.shape_combo.currentTextChanged.connect(self._tool_changed)
        self._update_color()

    @property
    def selection(self) -> AreaSelection | None:
        """
        Snapshot graphics into immutable coordinates for worker threads.
        """
        if self._roi is None or self._points:
            return None
        if self._kind == "Polygon":
            points = tuple((float(point.x()), float(point.y()))
                           for _, point in self._roi.getSceneHandlePositions())
            assert self._viewer is not None
            points = tuple((float(p.x()), float(p.y())) for p in
                           (self._viewer.image_item.mapFromScene(*point) for point in points))
            return AreaSelection(self._kind, points)
        position, size = self._roi.pos(), self._roi.size()
        return AreaSelection(self._kind, ((float(position.x()), float(position.y())),
                                         (float(position.x() + size.x()), float(position.y() + size.y()))))

    def bind(self, viewer: FischImageViewer) -> None:
        """
        Observe plain left gestures while leaving Ctrl navigation to the viewer.
        """
        self._viewer = viewer
        viewport = cast(QWidget, viewer.canvas.viewport())
        viewport.installEventFilter(self)
        viewport.setMouseTracking(True)

    def reset(self, shape: tuple[int, int] = (0, 0)) -> None:
        """
        Clear selection when changing images and enable drawing for valid images.
        """
        self._shape = shape
        self._start = None
        self._points = []
        self.clear()
        self.setEnabled(all(shape))

    def clear(self) -> None:
        """
        Remove the selection and restore pixel-hover measurement.
        """
        if self._roi is not None and self._viewer is not None:
            self._viewer.view_box.removeItem(self._roi)
        self._roi = None
        self._points = []
        self.changed.emit()
        self.finished.emit()

    def set_rectangle(self, bounds: tuple[int, int, int, int]) -> None:
        """
        Accept an automatically fitted crop as the shared selection.
        """
        left, top, right, bottom = bounds
        self._create_roi("Rectangle", ((left, top), (right, bottom)))
        self.finished.emit()

    def _create_roi(self, kind: str, points: tuple[tuple[float, float], ...]) -> None:
        """
        Replace the graphics with a shape offering native move and resize handles.
        """
        if self._viewer is None:
            return
        self._muted = True
        if self._roi is not None:
            self._viewer.view_box.removeItem(self._roi)
        self._kind = kind
        if kind == "Polygon":
            self._roi = pg.PolyLineROI(points, closed=True, pen=pg.mkPen(self._color, width=2),
                                      maxBounds=QRectF(0, 0, self._shape[1], self._shape[0]))
        else:
            (left, top), (right, bottom) = points
            roi_type = pg.EllipseROI if kind == "Ellipse" else pg.RectROI
            self._roi = roi_type((left, top), (max(1, right - left), max(1, bottom - top)),
                                 pen=pg.mkPen(self._color, width=2),
                                 maxBounds=QRectF(0, 0, self._shape[1], self._shape[0]))
            if kind == "Rectangle":
                for handle, centre in [((0, 0), (1, 1)), ((0, 1), (1, 0)),
                                       ((1, 0), (0, 1)), ((0, 0.5), (1, 0.5)),
                                       ((1, 0.5), (0, 0.5)), ((0.5, 0), (0.5, 1)),
                                       ((0.5, 1), (0.5, 0))]:
                    self._roi.addScaleHandle(handle, centre)
        self._roi.setZValue(85)
        self._viewer.view_box.addItem(self._roi, ignoreBounds=True)
        self._roi.sigRegionChanged.connect(self._region_changed)
        self._roi.sigRegionChangeFinished.connect(self._region_finished)
        self._muted = False
        self.changed.emit()

    def _region_changed(self) -> None:
        """
        Refresh current-plane measurement while a native handle is being dragged.
        """
        if not self._muted:
            self.changed.emit()

    def _region_finished(self) -> None:
        """
        Publish a final selection for profiles and existing mask selection.
        """
        self.finished.emit()
        selection = self.selection
        if selection is not None and selection.kind == "Rectangle":
            self.rectangle_selected.emit(selection.bounds(self._shape))

    def _tool_changed(self, text: str) -> None:
        """
        End unfinished polygon input when changing drawing tools.
        """
        if self._points:
            self.clear()

    def _choose_color(self) -> None:
        """
        Change only the selection outline colour.
        """
        color = QColorDialog.getColor(self._color, self, "Shape colour")
        if color.isValid():
            self._color = color
            self._update_color()

    def _update_color(self) -> None:
        """
        Apply the shared colour to the control and current outline.
        """
        self.color_button.setStyleSheet(f"background-color: {self._color.name()}; color: black;")
        if self._roi is not None:
            self._roi.setPen(pg.mkPen(self._color, width=2))

    def _hit(self, x: float, y: float) -> str:
        """
        Identify shape interiors and rectangle/ellipse edges in image coordinates.
        """
        area = self.selection
        if area is None or self._viewer is None:
            return "draw"
        xx, yy = zip(*area.points)
        left, right, top, bottom = min(xx), max(xx), min(yy), max(yy)
        px, py = self._viewer.view_box.viewPixelSize()
        tx, ty = abs(px) * 6, abs(py) * 6
        if area.kind != "Polygon" and left - tx <= x <= right + tx and top - ty <= y <= bottom + ty:
            horizontal = "left" if abs(x - left) < tx else "right" if abs(x - right) < tx else ""
            vertical = "top" if abs(y - top) < ty else "bottom" if abs(y - bottom) < ty else ""
            if horizontal or vertical:
                return "_".join(part for part in (horizontal, vertical) if part)
        if area.kind == "Polygon":
            polygon = QPolygonF([QPointF(a, b) for a, b in area.points])
            inside = polygon.containsPoint(QPointF(x, y), Qt.FillRule.OddEvenFill)
        elif area.kind == "Ellipse":
            inside = (((x - (left + right) / 2) / max((right - left) / 2, 1e-9)) ** 2
                      + ((y - (top + bottom) / 2) / max((bottom - top) / 2, 1e-9)) ** 2 <= 1)
        else:
            inside = left <= x <= right and top <= y <= bottom
        return "move" if inside else "draw"

    def _drag_shape(self, x: float, y: float) -> None:
        """
        Move or resize the existing shape with one coherent geometry update.
        """
        if self._original is None or self._roi is None or self._start is None:
            return
        xx, yy = zip(*self._original.points)
        left, right, top, bottom = min(xx), max(xx), min(yy), max(yy)
        if self._gesture.startswith("vertex_"):
            points = list(self._original.points)
            points[int(self._gesture.split("_")[1])] = (x, y)
            self._create_roi("Polygon", tuple(points))
        elif self._gesture == "move":
            dx = min(max(x - self._start.x(), -left), self._shape[1] - right)
            dy = min(max(y - self._start.y(), -top), self._shape[0] - bottom)
            self._roi.setPos((self._original_pos[0] + dx, self._original_pos[1] + dy))
        else:
            x, y = round(x), round(y)
            if "left" in self._gesture:
                left = min(x, right - 1)
            if "right" in self._gesture:
                right = max(x, left + 1)
            if "top" in self._gesture:
                top = min(y, bottom - 1)
            if "bottom" in self._gesture:
                bottom = max(y, top + 1)
            self._roi.setPos((left, top), update=False)
            self._roi.setSize((right - left, bottom - top))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """
        Draw in empty space; allow native ROI handles to move existing shapes.
        """
        viewer = self._viewer
        if viewer is None or not all(self._shape) or not isinstance(event, QMouseEvent):
            return False
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier or self._control_start is not None:
            if event.type() == QEvent.Type.MouseButtonPress:
                self._control_start = event.position()
                if self._roi is not None:
                    self._roi.setEnabled(False)
            elif event.type() == QEvent.Type.MouseButtonRelease and self._control_start is not None:
                if self._roi is not None:
                    roi = self._roi
                    QTimer.singleShot(0, lambda: roi.setEnabled(True))
                self._control_start = None
            self._start = None
            return False
        if viewer._loading_visible:
            self._start = None
            return False
        scene = viewer.canvas.mapToScene(cast(Any, event.position().toPoint()))
        point = viewer.view_box.mapSceneToView(scene)
        x = min(max(float(point.x()), 0), self._shape[1])
        y = min(max(float(point.y()), 0), self._shape[0])
        kind = self.shape_combo.currentText()
        if event.type() == QEvent.Type.MouseButtonDblClick and kind == "Polygon":
            if len(self._points) >= 3:
                points = tuple(self._points)
                self._points = []
                self._create_roi("Polygon", points)
                self._region_finished()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if not viewer.view_box.sceneBoundingRect().contains(scene):
                return False
            if self._roi is not None and not self._points:
                if self._kind == "Polygon":
                    for index, (_, handle) in enumerate(self._roi.getSceneHandlePositions()):
                        if (handle - scene).manhattanLength() < 10:
                            self._start, self._start_screen = QPointF(x, y), event.position()
                            self._original = self.selection
                            self._gesture, self._dragged = f"vertex_{index}", False
                            return True
                hit = self._hit(x, y)
                if hit != "draw":
                    self._start, self._start_screen = QPointF(x, y), event.position()
                    self._original = self.selection
                    self._original_pos = (self._roi.pos().x(), self._roi.pos().y())
                    self._gesture, self._dragged = hit, False
                    return True
            if kind == "Polygon":
                if self._roi is not None and not self._points:
                    self.clear()
                if not self._points or hypot(x - self._points[-1][0], y - self._points[-1][1]) > 0.5:
                    self._points.append((x, y))
                if len(self._points) > 1:
                    self._create_roi("Polygon", tuple(self._points))
                return True
            self._start = QPointF(x, y)
            self._start_screen = event.position()
            self._dragged = False
            self._new_roi = False
            self._gesture = "draw"
            return True
        if event.type() == QEvent.Type.MouseMove and self._start is not None:
            if (event.position() - self._start_screen).manhattanLength() >= QApplication.startDragDistance():
                self._dragged = True
            if self._dragged:
                if self._gesture == "draw":
                    left, top = min(self._start.x(), x), min(self._start.y(), y)
                    right, bottom = max(self._start.x(), x), max(self._start.y(), y)
                    if not self._new_roi:
                        self._create_roi(kind, ((left, top), (right, bottom)))
                        self._new_roi = True
                    else:
                        self._roi.setPos((left, top), update=False)
                        self._roi.setSize((max(1, right - left), max(1, bottom - top)))
                else:
                    self._drag_shape(x, y)
            return True
        if event.type() == QEvent.Type.MouseButtonRelease and self._start is not None:
            if not self._dragged and self._gesture == "draw":
                self.clear()
                self.cell_clicked.emit(self._start)
            else:
                self._region_finished()
            self._start = None
            return True
        return False
