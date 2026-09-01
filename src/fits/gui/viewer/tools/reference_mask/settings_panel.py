from __future__ import annotations

from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from fits.gui.viewer.image_viewer import DrawingMode, DrawingOperation, DrawingTool


class ReferenceMaskPanel(QWidget):
    """Configure interactive reference-mask drawing and saving."""

    drawing_options_changed = Signal()
    apply_requested = Signal()
    cancel_requested = Signal()
    undo_requested = Signal()
    clear_requested = Signal()
    save_requested = Signal()
    mask_visibility_changed = Signal(bool)
    mask_opacity_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edit_dirty = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Reference mask drawing")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        description = QLabel(
            "Draw binary reference masks on selected image planes. Replace "
            "commits on mouse release; Edit requires Apply.")
        description.setWordWrap(True)
        description.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(description)

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("e.g. nucleus")
        form.addRow("Reference label", self.label_edit)

        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.replace_mode = QRadioButton("Replace")
        self.replace_mode.setChecked(True)
        mode_layout.addWidget(self.replace_mode)
        self.edit_mode = QRadioButton("Edit")
        mode_layout.addWidget(self.edit_mode)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.replace_mode)
        self.mode_group.addButton(self.edit_mode)
        form.addRow("Drawing mode", mode_widget)

        self.tool_combo = QComboBox()
        self.tool_combo.addItem("Free-hand", "freehand")
        self.tool_combo.addItem("Circle", "circle")
        self.tool_combo.addItem("Square", "square")
        self.tool_combo.addItem("Triangle", "triangle")
        form.addRow("Drawing tool", self.tool_combo)

        self.brush_size = QSpinBox()
        self.brush_size.setRange(1, 101)
        self.brush_size.setSingleStep(2)
        self.brush_size.setValue(5)
        self.brush_size.setSuffix(" px")
        form.addRow("Brush size", self.brush_size)

        operation_widget = QWidget()
        operation_layout = QHBoxLayout(operation_widget)
        operation_layout.setContentsMargins(0, 0, 0, 0)
        self.add_operation = QRadioButton("Add")
        self.add_operation.setChecked(True)
        operation_layout.addWidget(self.add_operation)
        self.erase_operation = QRadioButton("Erase")
        operation_layout.addWidget(self.erase_operation)
        self.operation_group = QButtonGroup(self)
        self.operation_group.addButton(self.add_operation)
        self.operation_group.addButton(self.erase_operation)
        form.addRow("Edit operation", operation_widget)
        self.operation_widget = operation_widget
        controls_layout.addLayout(form)

        edit_actions = QHBoxLayout()
        self.apply_button = QPushButton("Apply drawing")
        self.apply_button.clicked.connect(self.apply_requested)
        edit_actions.addWidget(self.apply_button)
        self.cancel_button = QPushButton("Cancel changes")
        self.cancel_button.clicked.connect(self.cancel_requested)
        edit_actions.addWidget(self.cancel_button)
        controls_layout.addLayout(edit_actions)

        self.clear_button = QPushButton("Clear current plane")
        self.clear_button.clicked.connect(self.clear_requested)
        drawing_actions = QHBoxLayout()
        self.undo_button = QPushButton("Undo drawing")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_requested)
        drawing_actions.addWidget(self.undo_button)
        drawing_actions.addWidget(self.clear_button)
        controls_layout.addLayout(drawing_actions)

        interpolation_title = QLabel("Interpolation")
        interpolation_title.setStyleSheet("font-weight: bold;")
        controls_layout.addWidget(interpolation_title)
        self.interpolate = QCheckBox("Fill missing masks when saving")
        self.interpolate.setChecked(True)
        controls_layout.addWidget(self.interpolate)
        interpolation_form = QFormLayout()
        self.interpolation_axis = QComboBox()
        interpolation_form.addRow("Axis", self.interpolation_axis)
        self.extrapolate_start = QCheckBox("Extend to first plane")
        self.extrapolate_start.setChecked(True)
        interpolation_form.addRow("Start", self.extrapolate_start)
        self.extrapolate_end = QCheckBox("Extend to last plane")
        self.extrapolate_end.setChecked(True)
        interpolation_form.addRow("End", self.extrapolate_end)
        self.interpolation_controls = QWidget()
        self.interpolation_controls.setLayout(interpolation_form)
        controls_layout.addWidget(self.interpolation_controls)
        controls_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(controls)
        layout.addWidget(scroll, 1)

        overlay_layout = QHBoxLayout()
        overlay_layout.addWidget(QLabel("Mask overlay"))
        self.show_mask = QCheckBox()
        self.show_mask.setChecked(True)
        self.show_mask.toggled.connect(self.mask_visibility_changed)
        overlay_layout.addWidget(self.show_mask)
        self.mask_opacity = QSlider(Qt.Orientation.Horizontal)
        self.mask_opacity.setRange(0, 100)
        self.mask_opacity.setValue(45)
        self.mask_opacity.valueChanged.connect(
            lambda value: self.mask_opacity_changed.emit(value / 100.0))
        overlay_layout.addWidget(self.mask_opacity, 1)
        layout.addLayout(overlay_layout)

        self.save_button = QPushButton("Save reference mask")
        self.save_button.clicked.connect(self.save_requested)
        layout.addWidget(self.save_button)

        for button in (self.replace_mode, self.edit_mode,
                       self.add_operation, self.erase_operation):
            button.toggled.connect(self._options_changed)
        self.tool_combo.currentIndexChanged.connect(self._options_changed)
        self.brush_size.valueChanged.connect(self._options_changed)
        self.interpolate.toggled.connect(self._refresh_interpolation_controls)
        self._refresh_mode_controls()
        self._refresh_interpolation_controls()

    @property
    def drawing_mode(self) -> DrawingMode:
        return "edit" if self.edit_mode.isChecked() else "replace"

    @property
    def drawing_tool(self) -> DrawingTool:
        return cast(DrawingTool, self.tool_combo.currentData())

    @property
    def drawing_operation(self) -> DrawingOperation:
        if self.drawing_mode == "replace":
            return "add"
        return "erase" if self.erase_operation.isChecked() else "add"

    @property
    def reference_label(self) -> str:
        return self.label_edit.text().strip()

    @property
    def selected_interpolation_axis(self) -> str | None:
        if not self.interpolate.isChecked():
            return None
        return cast(str, self.interpolation_axis.currentData())

    @property
    def edit_dirty(self) -> bool:
        return self._edit_dirty

    def set_available_axes(self, axes: str, shape: tuple[int, ...]) -> None:
        """Offer only interpolation axes containing more than one mask plane."""
        self.interpolation_axis.clear()
        for axis, label in (("T", "Time"), ("Z", "Z")):
            if axis in axes and shape[axes.index(axis)] > 1:
                self.interpolation_axis.addItem(label, axis)
        available = self.interpolation_axis.count() > 0
        self.interpolate.setEnabled(available)
        if not available:
            self.interpolate.setChecked(False)
        self._refresh_interpolation_controls()

    def set_edit_dirty(self, dirty: bool) -> None:
        self._edit_dirty = dirty
        self._refresh_mode_controls()

    def set_undo_available(self, available: bool) -> None:
        """Enable Undo when the current plane has drawing history."""
        self.undo_button.setEnabled(available)

    def _options_changed(self, *_: object) -> None:
        self._refresh_mode_controls()
        self.drawing_options_changed.emit()

    def _refresh_mode_controls(self) -> None:
        edit = self.drawing_mode == "edit"
        dirty = getattr(self, "_edit_dirty", False)
        self.replace_mode.setEnabled(not dirty)
        self.operation_widget.setEnabled(edit)
        self.apply_button.setEnabled(edit and dirty)
        self.cancel_button.setEnabled(edit and dirty)

    def _refresh_interpolation_controls(self, *_: object) -> None:
        self.interpolation_controls.setEnabled(
            self.interpolate.isChecked() and self.interpolate.isEnabled())
