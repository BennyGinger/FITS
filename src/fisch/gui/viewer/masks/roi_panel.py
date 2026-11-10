from __future__ import annotations

from typing import cast

import numpy as np
import pyqtgraph as pg
from numpy.typing import NDArray
from PySide6.QtCore import QObject, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fisch.gui.settings.wheel_widgets import (
    FocusWheelDoubleSpinBox, FocusWheelSpinBox,)
from fisch.gui.viewer.masks.reference_panel import ReferenceMaskPanel


class RoiMaskPanel(ReferenceMaskPanel):
    """Reference-style mask editor with an interactive threshold starting point."""

    DEFAULT_INTERPOLATION_ENABLED = False

    automatic_current_requested = Signal()
    automatic_stack_requested = Signal()
    threshold_changed = Signal(float, float)
    manual_stack_requested = Signal(float, float)
    fill_holes_requested = Signal()
    remove_small_objects_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Build compact ROI controls with one shared threshold range.
        """
        super().__init__(parent)
        self.title_label.setText("ROI mask")
        self.description_label.setText(
            "Select the image area whose pixels should be included in the analysis.")
        self.label_edit.setPlaceholderText("e.g. tail")
        self.label_edit.setToolTip(
            "Label used to save the mask as proc_roi_{label}.tif")
        self.save_button.setText("Save mask")
        self.mode_row.hide()
        self.edit_mode.setChecked(True)
        threshold_box, threshold_layout = self._section("Threshold")
        self.threshold_plot = pg.PlotWidget()
        self.threshold_plot.setMaximumHeight(95)
        self.threshold_plot.hideAxis("left")
        self.threshold_plot.setMouseEnabled(x=False, y=False)
        self.histogram_curve = self.threshold_plot.plot(
            [], [], stepMode="left", fillLevel=0,
            brush=(100, 170, 255, 80), pen=(100, 170, 255))
        self.threshold_region = pg.LinearRegionItem()
        self.threshold_plot.addItem(self.threshold_region)
        threshold_layout.addWidget(cast(QWidget, self.threshold_plot))
        current_values = QHBoxLayout()
        self.current_minimum = self._threshold_spin()
        self.current_minimum.setFixedWidth(90)
        current_values.addWidget(self.current_minimum)
        current_values.addWidget(QLabel("Minimum"))
        current_values.addStretch(1)
        self.apply_stack_button = QPushButton("Apply to stack")
        self.apply_stack_button.setFixedWidth(self.BUTTON_WIDTH)
        self.apply_stack_button.setToolTip("Apply the visible Minimum and Maximum thresholds to the whole stack.")
        self.apply_stack_button.clicked.connect(
            lambda: self.manual_stack_requested.emit(self.current_minimum.value(), self.current_maximum.value()))
        current_values.addWidget(self.apply_stack_button)
        current_values.addStretch(1)
        current_values.addWidget(QLabel("Maximum"))
        self.current_maximum = self._threshold_spin()
        self.current_maximum.setFixedWidth(90)
        current_values.addWidget(self.current_maximum)
        threshold_layout.addLayout(current_values)
        self.current_minimum.editingFinished.connect(self._current_values_edited)
        self.current_maximum.editingFinished.connect(self._current_values_edited)
        automatic_row = QHBoxLayout()
        automatic_label = QLabel("Automatic threshold")
        automatic_row.addWidget(automatic_label)
        automatic_row.addStretch(1)
        self.automatic_current_button = QPushButton("Current plane")
        self.automatic_current_button.setFixedWidth(120)
        self.automatic_current_button.clicked.connect(self.automatic_current_requested)
        automatic_row.addWidget(self.automatic_current_button)
        self.automatic_stack_button = QPushButton("Stack")
        self.automatic_stack_button.setFixedWidth(120)
        self.automatic_stack_button.clicked.connect(self.automatic_stack_requested)
        automatic_row.addWidget(self.automatic_stack_button)
        threshold_layout.addLayout(automatic_row)
        self.controls_layout.insertWidget(1, threshold_box)
        self.threshold_region.sigRegionChanged.connect(self._sync_threshold_values)
        self.threshold_region.sigRegionChangeFinished.connect(self._emit_threshold)
        self._image_range = (0.0, 1.0)

        cleanup, cleanup_layout = self._section("Mask cleanup — whole stack (selected channel)")
        fill_row = QHBoxLayout()
        fill_row.addWidget(QLabel("Fill holes"))
        fill_row.addStretch(1)
        self.fill_holes_button = QPushButton("Fill")
        self.fill_holes_button.setToolTip(
            "Fill holes in every time/Z plane of the selected channel, preserving manually erased pixels.")
        self.fill_holes_button.setFixedWidth(self.BUTTON_WIDTH)
        self.fill_holes_button.clicked.connect(self.fill_holes_requested)
        fill_row.addWidget(self.fill_holes_button)
        cleanup_layout.addLayout(fill_row)
        object_row = QHBoxLayout()
        object_row.addWidget(QLabel("Remove small object:"))
        object_row.addStretch(1)
        object_row.addWidget(QLabel("Min size"))
        self.minimum_object_size = FocusWheelSpinBox()
        self.minimum_object_size.setFixedWidth(110)
        self.minimum_object_size.setRange(1, 1_000_000_000)
        self.minimum_object_size.setValue(50)
        self.minimum_object_size.setSuffix(" px²")
        object_row.addWidget(self.minimum_object_size)
        self.remove_small_objects_button = QPushButton("Remove")
        self.remove_small_objects_button.setToolTip(
            "Remove small 2D objects in every time/Z plane of the selected channel.")
        self.remove_small_objects_button.setFixedWidth(self.BUTTON_WIDTH)
        self.remove_small_objects_button.clicked.connect(
            lambda: self.remove_small_objects_requested.emit(
                self.minimum_object_size.value()))
        object_row.addWidget(self.remove_small_objects_button)
        cleanup_layout.addLayout(object_row)
        self.controls_layout.insertWidget(
            self.controls_layout.indexOf(self.propagation_section), cleanup)

    @property
    def roi_label(self) -> str:
        return self.label_edit.text().strip()

    def set_threshold_image(self, image: NDArray[np.generic]) -> None:
        """
        Populate the histogram and visible thresholds from the current image.
        """
        values = np.asarray(image, dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return
        minimum, maximum = float(values.min()), float(values.max())
        if minimum == maximum:
            maximum = minimum + 1.0
        hist, edges = np.histogram(values, bins=min(256, max(2, int(np.sqrt(values.size)))))
        self.histogram_curve.setData(edges[:-1], hist)
        self._image_range = (minimum, maximum)
        blocker = QSignalBlocker(cast(QObject, self.threshold_region))
        self.threshold_region.setBounds((minimum, maximum))
        self.threshold_region.setRegion((minimum, maximum))
        del blocker
        self._set_current_values(minimum, maximum)

    def set_threshold_range(self, minimum: float, maximum: float) -> None:
        blocker = QSignalBlocker(cast(QObject, self.threshold_region))
        self.threshold_region.setRegion((minimum, maximum))
        del blocker
        self._set_current_values(minimum, maximum)

    def full_threshold_range(self) -> tuple[float, float]:
        return self._image_range

    def _sync_threshold_values(self) -> None:
        """
        Keep the visible threshold fields aligned with the histogram selection.
        """
        minimum, maximum = cast(tuple[float, float], self.threshold_region.getRegion())
        self._set_current_values(minimum, maximum)

    def _emit_threshold(self) -> None:
        minimum, maximum = cast(tuple[float, float], self.threshold_region.getRegion())
        self._set_current_values(minimum, maximum)
        self.threshold_changed.emit(minimum, maximum)

    def _current_values_edited(self) -> None:
        """
        Apply the visible threshold bounds to the current plane.
        """
        minimum, maximum = sorted(
            (self.current_minimum.value(), self.current_maximum.value()))
        self.set_threshold_range(minimum, maximum)
        self.threshold_changed.emit(minimum, maximum)

    def _set_current_values(self, minimum: float, maximum: float) -> None:
        minimum_blocker = QSignalBlocker(self.current_minimum)
        maximum_blocker = QSignalBlocker(self.current_maximum)
        self.current_minimum.setValue(minimum)
        self.current_maximum.setValue(maximum)
        del minimum_blocker, maximum_blocker

    @staticmethod
    def _threshold_spin() -> FocusWheelDoubleSpinBox:
        """
        Create an intensity input with two decimal places.
        """
        spin = FocusWheelDoubleSpinBox()
        spin.setDecimals(2)
        spin.setRange(-1e15, 1e15)
        spin.setKeyboardTracking(False)
        return spin
