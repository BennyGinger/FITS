"""Controls for one registration mode; action buttons belong to the window."""

from typing import cast

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QListWidget, QListWidgetItem
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from fits.gui.settings.wheel_widgets import FocusWheelComboBox, FocusWheelSpinBox
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.environment.constant import RegistrationContext
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.tasks.registration.tuned import Mode, RegistrationSettings


class RegistrationSettingsPanel(QWidget):
    changed = Signal()

    def __init__(self, mode: Mode) -> None:
        """Build preset controls, manual overrides and a final effective-settings summary."""
        super().__init__()
        self._updating = False
        self._crop_active = False
        self.mode = mode
        self._baseline: RegistrationSettings = (
            RegisterTimeSettings() if mode == "time" else RegisterChannelSettings())
        self._preset_context: RegistrationContext = cast(RegistrationContext, self._baseline.context)
        panel_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        contents = QWidget()
        outer = QVBoxLayout(contents)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.sections_layout = outer
        scroll.setWidget(contents)
        panel_layout.addWidget(scroll, 1)
        self.registration_group, settings_layout = self._section("Registration settings")
        outer.addWidget(self.registration_group)
        description = QLabel(
            "Fit drift from one channel, then apply the transforms to every channel and Z plane."
            if mode == "time" else
            "Fit each channel to the reference at the selected frame, then apply its "
            "transform throughout the movie.\n\n"
            "Use channels with recognizable corresponding structures and good signal. "
            "Different biological compartments or changing spatial patterns can mislead "
            "fitting. Prefer stable structural markers or calibration images, and verify "
            "each channel pair.")
        description.setWordWrap(True)
        settings_layout.addWidget(description)
        form = QFormLayout()
        settings_layout.addLayout(form)
        self.overwrite = QCheckBox("Overwrite existing pipeline output")
        form.addRow(self.overwrite)
        self.context = FocusWheelComboBox()
        for context in (["linear_drift", "rotational_drift", "complex_drift"] if mode == "time"
                        else ["channel_shift", "channel_shift_dual_cam", "channel_shift_complex"]):
            self.context.addItem(context, context)
        self.context.addItem("Custom", None)
        self.context.setToolTip("Choose a preset, or edit backend/method. Matching choices select their preset; others use Custom.")
        form.addRow("Context", self.context)
        self.manual_group = QGroupBox("Backend and method")
        manual_layout = QVBoxLayout(self.manual_group)
        self.manual_status = QLabel("Set by context")
        manual_layout.addWidget(self.manual_status)
        manual_form = QFormLayout()
        manual_layout.addLayout(manual_form)
        settings_layout.addWidget(self.manual_group)
        self.backend = FocusWheelComboBox()
        for backend in ("pystackreg", "cv2", "scikit"):
            self.backend.addItem(backend, backend)
        manual_form.addRow("Backend", self.backend)
        self.method = FocusWheelComboBox()
        for method in ("translation", "rigid_body", "affine"):
            self.method.addItem(method, method)
        manual_form.addRow("Method", self.method)
        form = QFormLayout()
        settings_layout.addLayout(form)
        self.channel = FocusWheelComboBox()
        form.addRow("Fitting channel" if mode == "time" else "Reference channel", self.channel)
        self.strategy = FocusWheelComboBox()
        self.strategy.addItems(["previous", "first", "mean"])
        self.reference_frame = FocusWheelSpinBox()
        self.reference_frame.setMinimum(1)
        self.reference_frame.setToolTip("Frame numbers start at 1 in this viewer.")
        self.excluded = QListWidget()
        self.excluded.setMaximumHeight(110)
        if mode == "time":
            form.addRow("Reference strategy", self.strategy)
        else:
            form.addRow("Reference frame", self.reference_frame)
            form.addRow("Exclude channels", self.excluded)
        self.crop_group, self.crop_layout = self._section("Fitting crop")
        self.crop_description = QLabel(
            "Use a stable area to help when full-image fitting is difficult. A smaller "
            "crop can also speed up live previews. Registration still applies to the "
            "full image, with unchanged output size.")
        self.crop_description.setWordWrap(True)
        self.crop_layout.addWidget(self.crop_description)
        outer.addWidget(self.crop_group)
        self.resolved_group, resolved_layout = self._section("Resolved registration")
        self.resolved = QLabel()
        self.resolved.setWordWrap(True)
        resolved_layout.addWidget(self.resolved)
        panel_layout.addWidget(self.resolved_group)
        outer.addStretch(1)
        self.context.currentIndexChanged.connect(self._context_changed)
        for combo in (self.backend, self.method):
            combo.currentIndexChanged.connect(self._manual_changed)
        for combo in (self.channel, self.strategy):
            combo.currentIndexChanged.connect(self._controls_changed)
        self.overwrite.toggled.connect(self._controls_changed)
        self.reference_frame.valueChanged.connect(self._controls_changed)
        self.excluded.itemChanged.connect(self._controls_changed)
        self._context_changed()

    @staticmethod
    def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
        """Build a separate bordered section matching SegTune's settings cards."""
        frame = QFrame()
        frame.setObjectName("settingsSection")
        frame.setAccessibleName(title)
        frame.setStyleSheet(
            "QFrame#settingsSection { background-color: #303030; "
            "border: 1px solid #555; border-radius: 4px; } "
            "QFrame#settingsSection QLabel, QFrame#settingsSection QCheckBox, "
            "QFrame#settingsSection QGroupBox { color: #e6e6e6; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(9, 7, 9, 9)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: bold; border: none; background: transparent;")
        layout.addWidget(heading)
        return frame, layout

    def _context_changed(self) -> None:
        """Apply a named preset, leaving manual choices intact for Custom."""
        if self._updating:
            return
        if self.context.currentData() is not None:
            self._preset_context = self.context.currentData()
            plan = resolve_registration_plan(self._preset_context)
            with QSignalBlocker(self.backend), QSignalBlocker(self.method):
                self.backend.setCurrentIndex(self.backend.findData(plan.backend))
                self.method.setCurrentIndex(self.method.findData(plan.method))
        self._controls_changed()

    def _match_context(self) -> None:
        """Select a preset matching the displayed backend and method, or Custom."""
        matching = None
        for index in range(self.context.count()):
            context = self.context.itemData(index)
            if context is None:
                continue
            plan = resolve_registration_plan(context)
            if plan.backend == self.backend.currentData() and plan.method == self.method.currentData():
                matching = context
                break
        with QSignalBlocker(self.context):
            self.context.setCurrentIndex(self.context.findData(matching))
        if matching is not None:
            self._preset_context = matching

    def _manual_changed(self) -> None:
        """Restore matching named contexts when manual choices return to a preset."""
        if self._updating:
            return
        self._match_context()
        self._controls_changed()

    def _controls_changed(self) -> None:
        """Refresh the effective-settings display and notify the owning tuner."""
        if self._updating:
            return
        self.manual_status.setText("Manual settings" if self.context.currentData() is None else "Set by context")
        self.update_resolved()
        self.changed.emit()

    def update_resolved(self, crop_active: bool | None = None) -> None:
        """Show the effective method, reference strategy and actual fitting scope."""
        if crop_active is not None:
            self._crop_active = crop_active
        try:
            plan = resolve_registration_plan(self._preset_context, self.backend.currentData(), self.method.currentData())
            if plan.backend == "scikit" and plan.method != "translation":
                raise ValueError("The scikit backend supports translation only.")
            reference = (self.strategy.currentText() if self.mode == "time" else
                         f"reference {self.channel.currentText() or 'not selected'}, frame {self.reference_frame.value()}")
            scope = "from crop" if self._crop_active else "full image"
            self.resolved.setText(f"{plan.backend} / {plan.method} / {reference} / {scope}")
        except ValueError as error:
            self.resolved.setText(str(error))

    def load(self, settings: RegistrationSettings, labels: tuple[str, ...], frames: int) -> None:
        """Load effective values and select their matching preset, or Custom."""
        self._updating = True
        self._baseline = settings.model_copy(deep=True)
        self._preset_context = cast(RegistrationContext, settings.context)
        effective = resolve_registration_plan(self._preset_context, settings.backend, settings.method)
        self.overwrite.setChecked(settings.overwrite)
        self.backend.setCurrentIndex(self.backend.findData(effective.backend))
        self.method.setCurrentIndex(self.method.findData(effective.method))
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
        self._match_context()
        self._updating = False
        self._controls_changed()

    def settings(self) -> RegistrationSettings:
        """Return CLI-compatible settings, retaining the last named context for Custom."""
        payload = {**self._baseline.model_dump(), "overwrite": self.overwrite.isChecked(),
                   "context": self._preset_context, "backend": self.backend.currentData(),
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
