"""Shared compartment controls for the combined segmentation tuner."""

from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QListWidget, QVBoxLayout, QWidget

from fisch.gui.settings.wheel_widgets import FocusWheelDoubleSpinBox
from fisch.settings.models import ExtractSettings


class CompartmentPanel(QWidget):
    """
    Edit shared geometry settings independently of the image background channel.
    """

    changed = Signal()

    def __init__(self, settings: ExtractSettings) -> None:
        """
        Build validated numerical controls and a read-only mask-channel list.
        """
        super().__init__()
        layout = QVBoxLayout(self)
        explanation = QLabel("Inspect membrane rings over any image channel. Geometry settings apply to every mask channel.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.enabled = QCheckBox()
        self.enabled.setChecked(settings.compartments)
        self.thickness = FocusWheelDoubleSpinBox()
        self.thickness.setDecimals(3)
        self.thickness.setRange(0.001, 100000)
        self.thickness.setValue(settings.membrane_thickness)
        self.dilation = FocusWheelDoubleSpinBox()
        self.dilation.setDecimals(3)
        self.dilation.setRange(0, 100000)
        self.dilation.setValue(settings.dilation_radius)
        self.save_masks = QCheckBox()
        self.save_masks.setChecked(settings.save_compartment_masks)
        form.addRow("Measure compartments", self.enabled)
        form.addRow("Membrane thickness (pixels)", self.thickness)
        form.addRow("Cell expansion (pixels)", self.dilation)
        form.addRow("Save compartment masks", self.save_masks)
        layout.addLayout(form)
        layout.addWidget(QLabel("Mask channels"))
        self.mask_channels = QListWidget()
        layout.addWidget(self.mask_channels, 1)
        self.source_label = QLabel("No mask loaded")
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        self.enabled.toggled.connect(self.changed)
        self.thickness.valueChanged.connect(self.changed)
        self.dilation.valueChanged.connect(self.changed)
        self.save_masks.toggled.connect(self.changed)

    def settings(self, baseline: ExtractSettings) -> ExtractSettings:
        """
        Preserve unrelated quantification options while validating edited values.
        """
        payload = {name: getattr(baseline, name) for name in type(baseline).model_fields}
        payload.update(compartments=self.enabled.isChecked(),
                       membrane_thickness=self.thickness.value(),
                       dilation_radius=self.dilation.value(),
                       save_compartment_masks=self.save_masks.isChecked(),
                       )
        return ExtractSettings.model_validate(payload)

    def set_settings(self, settings: ExtractSettings) -> None:
        """
        Load saved values without marking them edited or recalculating previews.
        """
        for widget, value in ((self.enabled, settings.compartments),
                              (self.save_masks, settings.save_compartment_masks)):
            with QSignalBlocker(widget):
                widget.setChecked(value)
        for widget, value in ((self.thickness, settings.membrane_thickness),
                              (self.dilation, settings.dilation_radius)):
            with QSignalBlocker(widget):
                widget.setValue(value)
