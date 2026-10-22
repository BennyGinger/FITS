"""Background parameters and a measurement-only rectangle using shared controls."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QListWidget, QListWidgetItem
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from fits.gui.settings.wheel_widgets import FocusWheelComboBox, FocusWheelDoubleSpinBox, FocusWheelSpinBox
from fits.gui.viewer.common.crop import CropPanel
from fits.settings.models import BGSubSettings


class BackgroundSettingsPanel(QWidget):
    """Edit processing parameters and report unscaled mean intensities."""

    changed = Signal()

    def __init__(self) -> None:
        """Build scrolling settings and measurement controls with pinned results."""
        super().__init__()
        self._baseline = BGSubSettings()
        self._loading = False
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        sections = QVBoxLayout(contents)
        group = QGroupBox("Background subtraction settings")
        layout = QVBoxLayout(group)
        description = QLabel("Preview background subtraction on the selected frame, channel and Z plane. "
                             "Only requested planes are processed; original data is preserved.")
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        layout.addLayout(form)
        self.overwrite = QCheckBox("Overwrite existing pipeline output")
        form.addRow(self.overwrite)
        self.window_size = FocusWheelSpinBox()
        self.window_size.setRange(2, 100000)
        self.window_size.setToolTip("SMO neighborhood size in pixels; at least 2, usually 3 or larger. "
                                   "Size 1 cannot distinguish background from foreground.")
        form.addRow("Window size", self.window_size)
        self.sigma = FocusWheelDoubleSpinBox()
        self.sigma.setRange(0, 10000)
        self.sigma.setDecimals(3)
        self.sigma.setToolTip("Gaussian smoothing sigma for background estimation; zero disables smoothing.")
        form.addRow("Sigma", self.sigma)
        self.threshold = FocusWheelDoubleSpinBox()
        self.threshold.setRange(0, 1)
        self.threshold.setDecimals(6)
        self.threshold.setSingleStep(0.01)
        self.threshold.setToolTip("SMO background decision threshold, matching the pipeline parameter.")
        form.addRow("Threshold", self.threshold)
        self.statistic = FocusWheelComboBox()
        self.statistic.addItems(["median", "mean"])
        form.addRow("Statistic", self.statistic)
        self.excluded = QListWidget()
        self.excluded.setMaximumHeight(110)
        self.excluded.setToolTip("Checked channels pass through without background subtraction.")
        form.addRow("Exclude channels", self.excluded)
        sections.addWidget(group)
        measurement_group = QGroupBox("Intensity measurement")
        measurement_layout = QVBoxLayout(measurement_group)
        explanation = QLabel("Draw a box to compare original and processed mean intensities. "
                             "The box measures pixels only; processing always uses the full plane.")
        explanation.setWordWrap(True)
        measurement_layout.addWidget(explanation)
        self.measurement = CropPanel(automatic=False)
        self.measurement.enabled.setText("Enable measurement box")
        self.measurement.enabled.setToolTip("Enable drawing, moving and resizing an intensity measurement box.")
        self.measurement.preview_button.setText("Zoom to box")
        measurement_layout.addWidget(self.measurement)
        sections.addWidget(measurement_group)
        sections.addStretch(1)
        scroll.setWidget(contents)
        outer.addWidget(scroll, 1)
        results = QGroupBox("Mean intensity in box")
        results_layout = QVBoxLayout(results)
        self.means = QLabel("Enable the measurement box and draw a rectangle.")
        self.means.setWordWrap(True)
        results_layout.addWidget(self.means)
        outer.addWidget(results)
        for widget in (self.window_size, self.sigma, self.threshold):
            widget.valueChanged.connect(self._edited)
        self.statistic.currentIndexChanged.connect(self._edited)
        self.excluded.itemChanged.connect(self._edited)
        self.overwrite.toggled.connect(self._edited)

    def _edited(self) -> None:
        """Notify the viewer after a user edit, excluding programmatic loading."""
        if not self._loading:
            self.changed.emit()

    def load(self, settings: BGSubSettings, labels: tuple[str, ...]) -> None:
        """Populate numerical settings while preserving unexposed execution options."""
        self._loading = True
        self._baseline = settings.model_copy(deep=True)
        self.overwrite.setChecked(settings.overwrite)
        self.window_size.setValue(settings.size)
        self.sigma.setValue(settings.sigma)
        self.threshold.setValue(settings.threshold)
        self.statistic.setCurrentText(settings.serialize_statistic_name())
        self.excluded.clear()
        for label in labels:
            item = QListWidgetItem(label, self.excluded)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if label in (settings.exclude_channel or ())
                               else Qt.CheckState.Unchecked)
        self._loading = False

    def settings(self) -> BGSubSettings:
        """Return validated settings, retaining runtime choices loaded from the GUI."""
        excluded = [self.excluded.item(i).text() for i in range(self.excluded.count())
                    if self.excluded.item(i).checkState() == Qt.CheckState.Checked]
        return BGSubSettings.model_validate({**{name: getattr(self._baseline, name) for name in BGSubSettings.model_fields},
            "size": self.window_size.value(),
            "sigma": self.sigma.value(), "threshold": self.threshold.value(),
            "statistic": self.statistic.currentText(), "exclude_channel": excluded or None,
            "overwrite": self.overwrite.isChecked()})
