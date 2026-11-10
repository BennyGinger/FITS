"""Profile plot navigation and independently editable axis ranges."""

from collections.abc import Callable
from typing import Any, cast

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QToolButton, QVBoxLayout, QWidget

from fisch.gui.settings.wheel_widgets import FocusWheelDoubleSpinBox
from fisch.gui.viewer.common.image_viewer import FischImageViewer


class ProfileAxis(pg.AxisItem):
    """
    Report double-clicks on an axis without changing normal pan and zoom gestures.
    """

    range_requested: Callable[[], None] | None = None

    def mouseClickEvent(self, event: Any) -> None:
        """
        Open range editing on a left double-click; retain other axis interactions.
        """
        if event.button() == Qt.MouseButton.LeftButton and event.double():
            event.accept()
            if self.range_requested is not None:
                self.range_requested()
        else:
            super().mouseClickEvent(event)


class AxisRangeDialog(QDialog):
    """
    Edit a finite increasing axis interval with explicit minimum and maximum values.
    """

    def __init__(self, axis: str, limits: tuple[float, float], parent: QWidget) -> None:
        """
        Initialize controls from the currently visible range.
        """
        super().__init__(parent)
        self.setWindowTitle(f"{axis.upper()} axis range")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.minimum = FocusWheelDoubleSpinBox()
        self.maximum = FocusWheelDoubleSpinBox()
        for field, value in zip((self.minimum, self.maximum), limits):
            field.setDecimals(10)
            field.setRange(-1e300, 1e300)
            field.setValue(value)
            field.setKeyboardTracking(False)
            field.setMinimumWidth(180)
        form.addRow("Minimum", self.minimum)
        form.addRow("Maximum", self.maximum)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.minimum.valueChanged.connect(self._update_accept)
        self.maximum.valueChanged.connect(self._update_accept)
        self._update_accept()

    def _update_accept(self) -> None:
        """
        Accept only increasing intervals while allowing the fields to be edited freely.
        """
        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert button is not None
        button.setEnabled(self.minimum.value() < self.maximum.value())


class ProfilePlot(pg.PlotWidget):
    """
    Offer Home and independent X/Y resets at the ends of the corresponding axes.
    """

    def __init__(self) -> None:
        """
        Build axis-aware controls with space reserved above and beside the graph.
        """
        self.x_axis = ProfileAxis("bottom")
        self.y_axis = ProfileAxis("left")
        super().__init__(axisItems={"bottom": self.x_axis, "left": self.y_axis})
        self.y_axis.setWidth(72)
        self.hideButtons()
        cast(Any, self.plotItem).layout.setContentsMargins(0, 30, 32, 0)
        viewport = cast(QWidget, self.viewport())
        self.home_button = QToolButton(viewport)
        self.home_button.setIcon(FischImageViewer._home_icon())
        self.home_button.setToolTip("Fit and centre the complete profile. Restore automatic X and Y ranges.")
        self.reset_x_button = QToolButton(viewport)
        self.reset_y_button = QToolButton(viewport)
        self.reset_x_button.setText("R")
        self.reset_y_button.setText("R")
        self.reset_x_button.setToolTip("Reset X axis to its automatic range")
        self.reset_y_button.setToolTip("Reset Y axis to its automatic range")
        for button in (self.home_button, self.reset_x_button, self.reset_y_button):
            button.setFixedSize(24, 24)
            button.setAutoRaise(True)
            button.setStyleSheet("QToolButton { background: #30373d; color: #e8edf2; "
                                "border: 1px solid #777; border-radius: 3px; font-weight: bold; } "
                                "QToolButton:hover { background: #526170; }")
            button.raise_()
        self.home_button.clicked.connect(self.fit_all)
        self.reset_x_button.clicked.connect(lambda: self.reset_axis("x"))
        self.reset_y_button.clicked.connect(lambda: self.reset_axis("y"))
        self.x_axis.range_requested = lambda: self.edit_axis("x")
        self.y_axis.range_requested = lambda: self.edit_axis("y")
        self.getViewBox().sigResized.connect(self._position_buttons)
        QTimer.singleShot(0, cast(QWidget, self), self._position_buttons)

    def fit_all(self) -> None:
        """
        Fit and centre every curve and continue following subsequent data updates.
        """
        view = self.getViewBox()
        view.enableAutoRange(x=True, y=True)
        view.updateAutoRange()

    def reset_axis(self, axis: str) -> None:
        """
        Restore automatic scaling on one axis without disturbing the other.
        """
        view = self.getViewBox()
        view.enableAutoRange(axis=axis, enable=True)
        view.updateAutoRange()

    def edit_axis(self, axis: str) -> None:
        """
        Apply a manual interval to one axis until its reset button or Home is used.
        """
        view = self.getViewBox()
        index = 0 if axis == "x" else 1
        limits = tuple(view.viewRange()[index])
        dialog = AxisRangeDialog(axis, (limits[0], limits[1]), cast(QWidget, self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if axis == "x":
                view.setXRange(dialog.minimum.value(), dialog.maximum.value(), padding=0)
            else:
                view.setYRange(dialog.minimum.value(), dialog.maximum.value(), padding=0)

    def _position_buttons(self) -> None:
        """
        Keep reset controls aligned to the axis ends when the graph resizes.
        """
        rect = self.getViewBox().sceneBoundingRect()
        top = self.mapFromScene(rect.topLeft())
        bottom = self.mapFromScene(rect.bottomRight())
        viewport = cast(QWidget, self.viewport())
        self.home_button.move(4, 3)
        self.reset_y_button.move(max(32, top.x() - 12), max(3, top.y() - 27))
        self.reset_x_button.move(min(viewport.width() - 28, bottom.x() + 4), bottom.y() - 12)
