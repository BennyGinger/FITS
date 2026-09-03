from __future__ import annotations

from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from fits.gui.viewer.image_viewer import DrawingMode, DrawingOperation, DrawingTool
from fits.gui.wheel_widgets import (
    FocusWheelComboBox, FocusWheelSlider, FocusWheelSpinBox,
)


class ReferenceMaskPanel(QWidget):
    """Configure immediate add/erase editing of distance-reference masks."""

    DEFAULT_INTERPOLATION_ENABLED = True
    CONTROL_WIDTH = 150
    BUTTON_WIDTH = 160

    drawing_options_changed = Signal()
    undo_requested = Signal()
    clear_requested = Signal()
    save_requested = Signal()
    mask_visibility_changed = Signal(bool)
    mask_opacity_changed = Signal(float)
    interpolation_preview_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel("Distance reference")
        self.title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.title_label)
        self.description_label = QLabel(
            "Mark the point, edge, or structure from which distance will be measured.")
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(self.description_label)

        controls = QWidget()
        self.controls_layout = QVBoxLayout(controls)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setSpacing(8)

        self.drawing_section, drawing_layout = self._section("Drawing")
        self.mode_row = QWidget()
        mode_row = QHBoxLayout(self.mode_row)
        mode_row.setContentsMargins(0, 0, 0, 0)
        self.mode_label = QLabel("Drawing mode")
        mode_row.addWidget(self.mode_label)
        self.replace_mode = QRadioButton("Replace")
        self.edit_mode = QRadioButton("Edit")
        self.replace_mode.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.replace_mode)
        self.mode_group.addButton(self.edit_mode)
        mode_row.addWidget(self.replace_mode)
        mode_row.addWidget(self.edit_mode)
        mode_row.addStretch(1)
        drawing_layout.addWidget(self.mode_row)

        drawing_row = QHBoxLayout()
        drawing_row.addWidget(QLabel("Drawing tool"))
        self.tool_combo = FocusWheelComboBox()
        self.tool_combo.setFixedWidth(self.CONTROL_WIDTH)
        self.tool_combo.addItem("Free-hand", "freehand")
        self.tool_combo.addItem("Open line", "line")
        self.tool_combo.addItem("Circle", "circle")
        self.tool_combo.addItem("Square", "square")
        self.tool_combo.addItem("Triangle", "triangle")
        drawing_row.addWidget(self.tool_combo)
        drawing_row.addSpacing(20)
        drawing_row.addWidget(QLabel("Brush size"))
        self.brush_size = FocusWheelSpinBox()
        self.brush_size.setFixedWidth(90)
        self.brush_size.setRange(1, 101)
        self.brush_size.setSingleStep(2)
        self.brush_size.setValue(5)
        self.brush_size.setSuffix(" px")
        drawing_row.addWidget(self.brush_size)
        drawing_row.addStretch(1)
        drawing_layout.addLayout(drawing_row)

        drawing_actions = QHBoxLayout()
        self.undo_button = QPushButton("Undo")
        self.undo_button.setEnabled(False)
        self.undo_button.setFixedWidth(self.BUTTON_WIDTH)
        self.undo_button.clicked.connect(self.undo_requested)
        self.clear_button = QPushButton("Clear this plane")
        self.clear_button.setFixedWidth(self.BUTTON_WIDTH)
        self.clear_button.clicked.connect(self.clear_requested)
        drawing_actions.addWidget(self.undo_button)
        drawing_actions.addWidget(self.clear_button)
        drawing_actions.addStretch(1)
        drawing_layout.addLayout(drawing_actions)
        self.controls_layout.addWidget(self.drawing_section)

        self.propagation_section, propagation_layout = self._section("Propagation")
        self.interpolation_title = self.propagation_section.findChild(
            QLabel, "sectionTitle")
        interpolation_top = QHBoxLayout()
        self.interpolate = QCheckBox("Propagate drawings")
        self.interpolate.setChecked(self.DEFAULT_INTERPOLATION_ENABLED)
        self._interpolation_available = False
        interpolation_top.addWidget(self.interpolate)
        interpolation_top.addSpacing(16)
        interpolation_top.addWidget(QLabel("Axis"))
        self.interpolation_axis = FocusWheelComboBox()
        self.interpolation_axis.setFixedWidth(self.CONTROL_WIDTH)
        interpolation_top.addWidget(self.interpolation_axis)
        interpolation_top.addStretch(1)
        propagation_layout.addLayout(interpolation_top)
        extension_row = QHBoxLayout()
        self.extrapolate_start = QCheckBox("Extend to first plane")
        self.extrapolate_start.setChecked(True)
        extension_row.addWidget(self.extrapolate_start)
        extension_row.addSpacing(24)
        self.extrapolate_end = QCheckBox("Extend to last plane")
        self.extrapolate_end.setChecked(True)
        extension_row.addWidget(self.extrapolate_end)
        extension_row.addStretch(1)
        self.interpolation_controls = QWidget()
        self.interpolation_controls.setLayout(extension_row)
        propagation_layout.addWidget(self.interpolation_controls)
        self.live_preview = QPushButton("Live preview")
        self.live_preview.setCheckable(True)
        self.live_preview.setToolTip(
            "Show or hide the propagated result without changing the drawn masks.")
        self.live_preview.setStyleSheet(
            "QPushButton:checked { background-color: #2a82da; color: white; "
            "border: 1px solid #7fc0ff; }")
        self.live_preview.setFixedWidth(self.BUTTON_WIDTH)
        propagation_layout.addWidget(self.live_preview, alignment=Qt.AlignmentFlag.AlignLeft)
        self.controls_layout.addWidget(self.propagation_section)
        self.controls_layout.addStretch(1)
        self.controls_scroll = QScrollArea()
        self.controls_scroll.setWidgetResizable(True)
        self.controls_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.controls_scroll.setWidget(controls)
        layout.addWidget(self.controls_scroll, 1)

        self.overlay_widget = QWidget()
        overlay = QHBoxLayout(self.overlay_widget)
        overlay.setContentsMargins(0, 0, 0, 0)
        overlay.addWidget(QLabel("Mask overlay"))
        self.show_mask = QCheckBox()
        self.show_mask.setChecked(True)
        self.show_mask.toggled.connect(self.mask_visibility_changed)
        overlay.addWidget(self.show_mask)
        self.mask_opacity = FocusWheelSlider(Qt.Orientation.Horizontal)
        self.mask_opacity.setRange(0, 100)
        self.mask_opacity.setValue(45)
        self.mask_opacity.valueChanged.connect(
            lambda value: self.mask_opacity_changed.emit(value / 100.0))
        overlay.addWidget(self.mask_opacity, 1)
        layout.addWidget(self.overlay_widget)

        self.saving_section, saving_layout = self._section("Saving")
        save_row = QHBoxLayout()
        save_row.addWidget(QLabel("File label"))
        self.label_edit = QLineEdit()
        self.label_edit.setFixedWidth(self.CONTROL_WIDTH)
        self.label_edit.setPlaceholderText("e.g. wound")
        self.label_edit.setToolTip(
            "Label used to save the mask as fits_ref_{label}.tif")
        save_row.addWidget(self.label_edit)
        self.save_button = QPushButton("Save mask")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_requested)
        save_row.addWidget(self.save_button, 1)
        saving_layout.addLayout(save_row)
        layout.addWidget(self.saving_section)

        self.tool_combo.currentIndexChanged.connect(self.drawing_options_changed)
        self.replace_mode.toggled.connect(self.drawing_options_changed)
        self.edit_mode.toggled.connect(self.drawing_options_changed)
        self.brush_size.valueChanged.connect(self.drawing_options_changed)
        self.label_edit.textChanged.connect(
            lambda text: self.save_button.setEnabled(bool(text.strip())))
        self.interpolate.toggled.connect(self._refresh_interpolation_controls)
        self.interpolate.toggled.connect(self.interpolation_preview_changed)
        self.interpolation_axis.currentIndexChanged.connect(
            self.interpolation_preview_changed)
        self.extrapolate_start.toggled.connect(self.interpolation_preview_changed)
        self.extrapolate_end.toggled.connect(self.interpolation_preview_changed)
        self.live_preview.toggled.connect(self.interpolation_preview_changed)
        self._refresh_interpolation_controls()

    @staticmethod
    def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("settingsSection")
        frame.setStyleSheet(
            "QFrame#settingsSection { background-color: #303030; "
            "border: 1px solid #555; border-radius: 4px; }")
        section_layout = QVBoxLayout(frame)
        section_layout.setContentsMargins(9, 7, 9, 9)
        section_layout.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        heading.setStyleSheet(
            "font-weight: bold; border: none; background: transparent;")
        section_layout.addWidget(heading)
        return frame, section_layout

    @property
    def drawing_mode(self) -> DrawingMode:
        return "replace" if self.replace_mode.isChecked() else "edit"

    @property
    def drawing_tool(self) -> DrawingTool:
        return cast(DrawingTool, self.tool_combo.currentData())

    @property
    def drawing_operation(self) -> DrawingOperation:
        return "add"

    @property
    def reference_label(self) -> str:
        return self.label_edit.text().strip()

    @property
    def selected_interpolation_axis(self) -> str | None:
        if not self.interpolate.isChecked():
            return None
        return cast(str, self.interpolation_axis.currentData())

    @property
    def interpolation_preview_enabled(self) -> bool:
        return (self.live_preview.isChecked()
                and self.preview_interpolation_axis is not None)

    @property
    def preview_interpolation_axis(self) -> str | None:
        """Return the selected axis while interpolation is enabled."""
        if not self.interpolate.isChecked() or not self.interpolation_axis.isEnabled():
            return None
        return cast(str, self.interpolation_axis.currentData())

    def set_available_axes(self, axes: str, shape: tuple[int, ...]) -> None:
        was_available = self._interpolation_available
        self.interpolation_axis.clear()
        for axis, label in (("T", "Time"), ("Z", "Z")):
            if axis in axes and shape[axes.index(axis)] > 1:
                self.interpolation_axis.addItem(label, axis)
        available = self.interpolation_axis.count() > 0
        self._interpolation_available = available
        self.interpolate.setEnabled(available)
        if not available:
            self.interpolate.setChecked(False)
        elif not was_available:
            self.interpolate.setChecked(self.DEFAULT_INTERPOLATION_ENABLED)
        self._refresh_interpolation_controls()

    def set_undo_available(self, available: bool) -> None:
        self.undo_button.setEnabled(available)

    def _refresh_interpolation_controls(self, *_: object) -> None:
        enabled = self.interpolate.isChecked() and self._interpolation_available
        self.interpolation_axis.setEnabled(enabled)
        self.interpolation_controls.setEnabled(enabled)
        self.live_preview.setEnabled(enabled)
        if not enabled:
            self.live_preview.setChecked(False)
