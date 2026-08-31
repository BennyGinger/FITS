from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from cellpose_kit.backend.versioning import get_cellpose_version
from fits.gui.viewer.tools.segmentation.cellpose_options import installed_model_options
from fits.settings.models import SegmentSettings


class CellposeSettingsPanel(QWidget):
    """
    Edit the compact Cellpose settings used by preview inference.
    """

    run_requested = Signal()
    apply_requested = Signal()
    mask_visibility_changed = Signal(bool)
    mask_opacity_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Cellpose settings")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        self.version_label = QLabel(self._version_text())
        self.version_label.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(self.version_label)
        self.model_options = installed_model_options()

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.builtin_model = QComboBox()
        self.builtin_model.addItems(self.model_options.built_in_models)
        self.builtin_model.setCurrentText(self.model_options.default_model)
        self._add_form_row(
            form,
            "Built-in model",
            self.builtin_model,
            "Cellpose model bundled with or downloadable by the installed Cellpose version.")
        custom_model_row = QWidget()
        custom_model_layout = QHBoxLayout(custom_model_row)
        custom_model_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_model = QLineEdit()
        self.custom_model.setPlaceholderText("Optional path to a trained model")
        custom_model_layout.addWidget(self.custom_model, 1)
        self.custom_model_button = QPushButton("Browse")
        self.custom_model_button.clicked.connect(self._browse_custom_model)
        custom_model_layout.addWidget(self.custom_model_button)
        self._add_form_row(
            form,
            "Custom model",
            custom_model_row,
            "Optional trained-model file. When provided, it takes precedence over the built-in model.")
        self.diameter = self._double_spin(0.0, 10000.0, 15.0)
        self._add_form_row(
            form,
            "Diameter",
            self.diameter,
            "Expected object diameter in pixels. Use 0 for automatic estimation; incorrect values can split or merge objects.")
        self.flow_threshold = self._double_spin(0.0, 10.0, 0.4)
        self._add_form_row(
            form,
            "Flow threshold",
            self.flow_threshold,
            "Maximum permitted flow error. Increase it to retain more ROIs; decrease it to reject more ill-shaped ROIs.")
        self.cellprob_threshold = self._double_spin(-6.0, 6.0, 0.0)
        self._add_form_row(
            form,
            "Cell probability",
            self.cellprob_threshold,
            "Pixels above this threshold seed masks. Decrease it for more or larger ROIs; increase it to suppress dim detections.")
        self.do_3d = QCheckBox()
        self._add_form_row(
            form,
            "Process in 3D",
            self.do_3d,
            "Run native 3D segmentation on the complete Z volume.")
        self.stitch_threshold = self._double_spin(0.0, 100.0, 0.0)
        self._add_form_row(
            form,
            "Stitch threshold",
            self.stitch_threshold,
            "When greater than 0 and native 3D is disabled, stitch 2D masks across adjacent Z planes.")
        self.anisotropy = self._double_spin(0.0, 100.0, 0.0)
        self._add_form_row(
            form,
            "Anisotropy (0 = auto)",
            self.anisotropy,
            "Z-to-XY sampling ratio for 3D segmentation; for example, use 2 when Z spacing is twice the XY spacing.")
        self.denoise = QCheckBox()
        self.denoise.setChecked(True)
        self._add_form_row(
            form,
            "Denoise",
            self.denoise,
            "Apply Cellpose restoration before segmentation when supported by the installed version.")
        self.nuclear_channel = QComboBox()
        self._add_form_row(
            form,
            "Nuclear channel",
            self.nuclear_channel,
            "Optional second image channel supplied as nuclear information where the Cellpose backend supports it.")
        controls_layout.addLayout(form)

        controls_layout.addStretch(1)

        self.controls_scroll = QScrollArea()
        self.controls_scroll.setWidgetResizable(True)
        self.controls_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.controls_scroll.setWidget(controls)
        layout.addWidget(self.controls_scroll, 1)

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

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Apply settings")
        self.apply_button.clicked.connect(self.apply_requested)
        buttons.addWidget(self.apply_button)
        self.run_button = QPushButton("Run preview")
        self.run_button.clicked.connect(self.run_requested)
        self.run_button.setDefault(True)
        buttons.addWidget(self.run_button)
        layout.addLayout(buttons)

    def set_channels(self, labels: tuple[str, ...], nuclear_channel: str | None) -> None:
        self.nuclear_channel.clear()
        self.nuclear_channel.addItem("None", None)
        for label in labels:
            self.nuclear_channel.addItem(label, label)
        index = self.nuclear_channel.findData(nuclear_channel)
        self.nuclear_channel.setCurrentIndex(max(index, 0))

    def set_settings(self, settings: SegmentSettings) -> None:
        user = settings.user_settings
        model_type = user.get("model_type")
        pretrained_model = user.get("pretrained_model")
        custom_model = ""
        if isinstance(pretrained_model, str) and pretrained_model:
            if pretrained_model in self.model_options.built_in_models:
                model_type = pretrained_model
            else:
                custom_model = pretrained_model
        if isinstance(model_type, str) and model_type in self.model_options.built_in_models:
            self.builtin_model.setCurrentText(model_type)
        else:
            self.builtin_model.setCurrentText(self.model_options.default_model)
            if isinstance(model_type, str) and model_type:
                custom_model = model_type
        self.custom_model.setText(custom_model)
        self.diameter.setValue(float(user.get("diameter", 15) or 0))
        self.flow_threshold.setValue(float(user.get("flow_threshold", 0.4)))
        self.cellprob_threshold.setValue(float(user.get("cellprob_threshold", 0.0)))
        self.do_3d.setChecked(bool(user.get("do_3D", False)))
        self.stitch_threshold.setValue(float(user.get("stitch_threshold", 0.0)))
        self.anisotropy.setValue(float(user.get("anisotropy", 0.0) or 0))
        self.denoise.setChecked(settings.do_denoise)

    def set_3d_available(self, available: bool) -> None:
        """
        Enable volume settings only when the source has multiple Z planes.
        """
        if not available:
            self.do_3d.setChecked(False)
            self.stitch_threshold.setValue(0.0)
            self.anisotropy.setValue(0.0)
        tooltip = "" if available else "Requires an image with more than one Z plane."
        for widget in (self.do_3d, self.stitch_threshold, self.anisotropy):
            widget.setEnabled(available)
            widget.setToolTip(tooltip)

    def user_settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = {
            "diameter": self.diameter.value(),
            "flow_threshold": self.flow_threshold.value(),
            "cellprob_threshold": self.cellprob_threshold.value(),
            "do_3D": self.do_3d.isChecked(),
            "stitch_threshold": self.stitch_threshold.value(),}
        custom_model = self.custom_model.text().strip()
        if self.model_options.backend == "v4":
            settings["pretrained_model"] = custom_model or self.builtin_model.currentText()
        else:
            settings["model_type"] = self.builtin_model.currentText()
            settings["pretrained_model"] = custom_model or False
        if self.anisotropy.value() > 0:
            settings["anisotropy"] = self.anisotropy.value()
        return settings

    @property
    def selected_nuclear_channel(self) -> str | None:
        return self.nuclear_channel.currentData()

    def set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.apply_button.setEnabled(not running)

    def _browse_custom_model(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose custom Cellpose model",
            self.custom_model.text(),
            "Cellpose models (*)",)
        if selected:
            self.custom_model.setText(selected)

    @staticmethod
    def _add_form_row(form: QFormLayout,
                      label_text: str,
                      widget: QWidget,
                      tooltip: str,
                      ) -> None:
        label = QLabel(label_text)
        label.setToolTip(tooltip)
        widget.setToolTip(tooltip)
        for child in widget.findChildren(QWidget):
            child.setToolTip(tooltip)
        form.addRow(label, widget)

    @staticmethod
    def _double_spin(minimum: float,
                     maximum: float,
                     value: float,
                     ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(3)
        widget.setValue(value)
        return widget

    @staticmethod
    def _version_text() -> str:
        try:
            installed = version("cellpose")
            backend = get_cellpose_version()
        except (PackageNotFoundError, RuntimeError, ValueError) as error:
            return f"Cellpose unavailable: {error}"
        return f"Installed Cellpose {installed} ({backend} backend)"
