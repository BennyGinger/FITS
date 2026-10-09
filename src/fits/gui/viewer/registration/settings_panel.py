"""Controls for one registration mode; action buttons belong to the window."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QLabel, QListWidget, QListWidgetItem,
    QSpinBox, QVBoxLayout, QWidget,
)

from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.tasks.registration.tuned import Mode, RegistrationSettings


class RegistrationSettingsPanel(QWidget):
    changed = Signal()

    def __init__(self, mode: Mode) -> None:
        super().__init__()
        self.mode = mode
        self._baseline: RegistrationSettings = (
            RegisterTimeSettings() if mode == "time" else RegisterChannelSettings())
        outer = QVBoxLayout(self)
        title = QLabel("Time registration" if mode == "time" else "Channel registration")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        outer.addWidget(title)
        description = QLabel(
            "Fit drift from one channel, then apply the transforms to every channel and Z plane."
            if mode == "time" else
            "Fit channel alignment at the reference frame, then apply it throughout the movie.")
        description.setWordWrap(True)
        outer.addWidget(description)
        form = QFormLayout()
        outer.addLayout(form)
        self.overwrite = QCheckBox("Overwrite existing pipeline output")
        form.addRow(self.overwrite)
        self.context = QComboBox()
        self.context.addItems(["linear_drift", "rotational_drift", "complex_drift"] if mode == "time"
                              else ["channel_shift", "channel_shift_dual_cam", "channel_shift_complex"])
        form.addRow("Context", self.context)
        self.backend = QComboBox()
        self.backend.addItem("From context", None)
        for backend in ("pystackreg", "cv2", "scikit"):
            self.backend.addItem(backend, backend)
        form.addRow("Backend", self.backend)
        self.method = QComboBox()
        self.method.addItem("From context", None)
        for method in ("translation", "rigid_body", "affine"):
            self.method.addItem(method, method)
        form.addRow("Method", self.method)
        self.channel = QComboBox()
        form.addRow("Fitting channel" if mode == "time" else "Reference channel", self.channel)
        self.strategy = QComboBox()
        self.strategy.addItems(["previous", "first", "mean"])
        self.reference_frame = QSpinBox()
        self.reference_frame.setMinimum(1)
        self.reference_frame.setToolTip("Frame numbers start at 1 in this viewer.")
        self.excluded = QListWidget()
        self.excluded.setMaximumHeight(110)
        if mode == "time":
            form.addRow("Reference strategy", self.strategy)
        else:
            form.addRow("Reference frame", self.reference_frame)
            form.addRow("Exclude channels", self.excluded)
        self.resolved = QLabel()
        self.resolved.setWordWrap(True)
        outer.addWidget(self.resolved)
        outer.addStretch(1)
        for combo in (self.context, self.backend, self.method, self.channel, self.strategy):
            combo.currentIndexChanged.connect(self.changed)
        self.overwrite.toggled.connect(self.changed)
        self.reference_frame.valueChanged.connect(self.changed)
        self.excluded.itemChanged.connect(self.changed)

    def load(self, settings: RegistrationSettings, labels: tuple[str, ...], frames: int) -> None:
        self._baseline = settings.model_copy(deep=True)
        self.overwrite.setChecked(settings.overwrite)
        self.context.setCurrentText(settings.context)
        self.backend.setCurrentIndex(max(0, self.backend.findData(settings.backend)))
        self.method.setCurrentIndex(max(0, self.method.findData(settings.method)))
        self.channel.clear()
        self.channel.addItems(list(labels))
        selected = settings.fit_channel if isinstance(settings, RegisterTimeSettings) else settings.reference_channel
        if isinstance(selected, int):
            self.channel.setCurrentIndex(selected if 0 <= selected < len(labels) else 0)
        elif selected in labels:
            self.channel.setCurrentText(selected)
        self.reference_frame.setMaximum(frames)
        if isinstance(settings, RegisterTimeSettings):
            self.strategy.setCurrentText(settings.reference_strategy)
        else:
            self.reference_frame.setValue(min(frames, settings.reference_frame + 1))
        self.excluded.clear()
        for label in labels:
            item = QListWidgetItem(label, self.excluded)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            excluded = isinstance(settings, RegisterChannelSettings) and label in (settings.exclude_channel or ())
            item.setCheckState(Qt.CheckState.Checked if excluded else Qt.CheckState.Unchecked)

    def settings(self) -> RegistrationSettings:
        payload = {**self._baseline.model_dump(), "overwrite": self.overwrite.isChecked(),
                   "context": self.context.currentText(), "backend": self.backend.currentData(),
                   "method": self.method.currentData()}
        if self.mode == "time":
            payload.update(fit_channel=self.channel.currentText(), reference_strategy=self.strategy.currentText())
            settings = RegisterTimeSettings.model_validate(payload)
        else:
            excluded = [self.excluded.item(i).text() for i in range(self.excluded.count())
                        if self.excluded.item(i).checkState() == Qt.CheckState.Checked]
            payload.update(reference_channel=self.channel.currentText(), exclude_channel=excluded or None,
                           reference_frame=self.reference_frame.value() - 1)
            settings = RegisterChannelSettings.model_validate(payload)
        plan = resolve_registration_plan(settings.context, settings.backend, settings.method)
        if plan.backend == "scikit" and plan.method != "translation":
            raise ValueError("The scikit backend supports translation only.")
        return settings
