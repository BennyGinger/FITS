"""Time/channel registration tuning in one standard FITS image viewer."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSignalBlocker, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from fits.environment.constant import FITS_ARRAY_NAME, StepName
from fits.gui.settings import SettingsAdapter
from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.common.information_dialog import REGISTRATION_HELP
from fits.gui.viewer.registration.settings_panel import RegistrationSettingsPanel
from fits.gui.viewer.registration.worker import RegistrationPreviewWorker
from fits.settings.loader import run_settings_path
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.tasks.registration.tuned import Mode, RegistrationSettings, load_tuning
from fits.tasks.registration.tuning import RegistrationPreview, RegistrationTuningSession


class RegistrationTunerWindow(ImageToolWindow):
    settings_applied = Signal(str, object)
    file_filters = (FITS_ARRAY_NAME,)
    help_gui = "RegTune"
    tool_help = REGISTRATION_HELP

    def __init__(self, experiments_dir: str | Path | None = None, *, mode: Mode = "time",
                 time_settings: RegisterTimeSettings | None = None,
                 channel_settings: RegisterChannelSettings | None = None,
                 time_enabled: bool = False, settings_path: Path | None = None,
                 parent: QWidget | None = None) -> None:
        self._provided = time_settings is not None or channel_settings is not None
        self._defaults: dict[Mode, RegistrationSettings] = {
            "time": time_settings or RegisterTimeSettings(),
            "channel": channel_settings or RegisterChannelSettings()}
        self._settings_path = settings_path
        self._general_adapter: SettingsAdapter | None = None
        self._general_path: Path | None = None
        self._session: RegistrationTuningSession | None = None
        self._thread: QThread | None = None
        self._worker: RegistrationPreviewWorker | None = None
        self._loading = False
        self._closing = False
        self._last_mode: Mode | None = None
        super().__init__(experiments_dir, parent)
        self.tabs.setCurrentIndex(0 if mode == "time" else 1)
        self.use_time.setChecked(time_enabled)
        self.overlay_label.hide()
        self.show_mask.hide()
        self.mask_opacity.hide()
        self.setWindowTitle("FITS Registration Tuner")
        self.resize(1500, 950)

    def _build_tools(self) -> QWidget:
        self.tool_panel = QWidget()
        layout = QVBoxLayout(self.tool_panel)
        self.tabs = QTabWidget()
        self.panels: dict[Mode, RegistrationSettingsPanel] = {
            "time": RegistrationSettingsPanel("time"), "channel": RegistrationSettingsPanel("channel")}
        self.tabs.addTab(self.panels["time"], "Time registration")
        self.tabs.addTab(self.panels["channel"], "Channel registration")
        layout.addWidget(self.tabs, 1)
        self.use_time = QCheckBox("Preview channels after time registration")
        self.use_time.setToolTip("Use the Time tab's settings first, matching pipeline order.")
        layout.addWidget(self.use_time)
        self.run_button = QPushButton("Run preview")
        self.save_button = QPushButton("Save current settings")
        self.save_button.setToolTip("Run a matching preview first. Saves general settings and this experiment's transforms.")
        self.complete_button = QPushButton("Complete session")
        self.complete_button.setStyleSheet(
            "QPushButton { background-color: #278342; color: white; font-weight: bold; padding: 8px 14px; }"
            "QPushButton:hover { background-color: #32964f; }")
        for button in (self.run_button, self.save_button, self.complete_button):
            layout.addWidget(button)
        return self.tool_panel

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        self.comparison = QComboBox()
        self.comparison.addItems(["Registered image", "Original image", "Overlay with reference"])
        self.comparison.setToolTip("Overlay: selected image in green, reference in magenta; each is auto-scaled.")
        layout.addWidget(self.comparison)

    def _connect_tools(self) -> None:
        self._composite_item = pg.ImageItem(axisOrder="row-major")
        self._composite_item.setZValue(1)
        self.image_viewer.view_box.addItem(self._composite_item)
        self._composite_item.hide()
        self.run_button.clicked.connect(self._run_preview)
        self.save_button.clicked.connect(self._save_settings)
        self.complete_button.clicked.connect(self.close)
        self.tabs.currentChanged.connect(self._settings_edited)
        self.use_time.toggled.connect(self._settings_edited)
        self.comparison.currentIndexChanged.connect(self._display_selection)
        for panel in self.panels.values():
            panel.changed.connect(self._settings_edited)

    def mode(self) -> Mode:
        return "time" if self.tabs.currentIndex() == 0 else "channel"

    def current_settings(self) -> RegistrationSettings:
        return self.panels[self.mode()].settings()

    def _upstream(self) -> RegisterTimeSettings | None:
        if self.mode() == "channel" and self.use_time.isChecked():
            return RegisterTimeSettings.model_validate(self.panels["time"].settings())
        return None

    def _general_settings(self, source: Path) -> None:
        if self._provided:
            return
        adapter = SettingsAdapter()
        path = self._settings_path
        root = self.directory_browser.root_path or source.parent
        if path is None:
            for directory in (source.parent, *source.parents):
                candidate = run_settings_path(directory)
                if candidate.is_file():
                    path = candidate
                    break
                if directory == root:
                    break
        if path is not None:
            adapter.load(path)
        else:
            adapter.run_dir = str(root)
        mapping = adapter.as_mapping()
        self._defaults = {
            "time": RegisterTimeSettings.model_validate(mapping["register_time"]["params"]),
            "channel": RegisterChannelSettings.model_validate(mapping["register_channel"]["params"])}
        self.use_time.setChecked(adapter.step_enabled(StepName.REGISTER_TIME))
        self._general_adapter = adapter
        self._general_path = path or run_settings_path(root)

    @Slot(object)
    def _path_selected(self, selected: object) -> None:
        if isinstance(selected, (str, Path)):
            source = Path(selected)
            self._open_source(source / FITS_ARRAY_NAME if source.is_dir() else source)

    def _open_source(self, source: Path) -> None:
        if source == self._source_path:
            return
        if self._thread is not None:
            self.status_label.setText("Wait for or cancel the preview before changing experiment.")
            return
        if source.name != FITS_ARRAY_NAME or not source.is_file():
            self.status_label.setText(f"Choose a folder containing {FITS_ARRAY_NAME}.")
            return
        self._close_session()
        self._last_mode = None
        self._loading = True
        try:
            self._general_settings(source)
            session = RegistrationTuningSession(source)
            self._session = session
            self._image_session = session
            self._source_path = source
            for mode, panel in self.panels.items():
                tuned = load_tuning(source, mode)
                panel.load(tuned.settings if tuned is not None else self._defaults[mode],
                           session.channel_labels, session.frame_count)
            with QSignalBlocker(self.channel_combo):
                self.channel_combo.clear()
                self.channel_combo.addItems(list(session.channel_labels))
            self.frame_slider.setRange(0, session.frame_count - 1)
            self.z_slider.setRange(0, session.plane_count - 1)
            self.frame_slider.setValue(0)
            self.z_slider.setValue(0)
            self._set_source_controls_enabled(True)
            self.status_label.setText(f"Loaded {source.parent.name}. Run preview to fit registration.")
        except Exception as error:
            self._close_session()
            self.status_label.setText(str(error))
        finally:
            self._loading = False
        self._settings_edited()

    @Slot()
    def _settings_edited(self) -> None:
        if self._loading:
            return
        self.use_time.setVisible(self.mode() == "channel")
        valid = False
        cached = None
        if self._session is not None:
            if self.mode() != self._last_mode:
                self._last_mode = self.mode()
                channel = self.panels[self.mode()].channel.currentIndex()
                if self.mode() == "channel":
                    channel = next((i for i in range(self.channel_combo.count()) if i != channel), 0)
                self.channel_combo.setCurrentIndex(channel)
                self.comparison.setCurrentIndex(2 if self.mode() == "channel" else 0)
            try:
                settings = self.current_settings()
                plan = resolve_registration_plan(settings.context, settings.backend, settings.method)
                self.panels[self.mode()].resolved.setText(f"Resolved: {plan.backend} / {plan.method}")
                cached = self._session.cached_preview(self.mode(), settings, self._upstream())
                valid = True
            except Exception as error:
                self.panels[self.mode()].resolved.setText(str(error))
        self.run_button.setText("Cancel preview" if self._thread is not None else "Run preview")
        self.run_button.setEnabled(valid or self._thread is not None)
        self.save_button.setEnabled(cached is not None and self._thread is None)
        self._display_selection()

    def _display_overlay(self, image, frame, channel, z_index) -> None:
        self._composite_item.hide()
        self.image_viewer.image_item.show()
        self.lut_controls.setEnabled(True)
        if self._session is None or self._loading:
            return
        try:
            settings = self.current_settings()
            preview = self._session.cached_preview(self.mode(), settings, self._upstream())
        except ValueError:
            return
        if preview is None or self.comparison.currentIndex() == 1:
            return
        selected = self._session._select_plane(preview.array, frame_index=frame,
                                               channel=channel, z_index=z_index)
        self.image_viewer.set_image(selected)
        if self.comparison.currentIndex() != 2:
            return
        if isinstance(settings, RegisterChannelSettings):
            reference_channel = settings.reference_channel if settings.reference_channel is not None else 0
            reference_frame = frame
        else:
            reference_channel = channel
            reference_frame = 0
        reference = self._session._select_plane(preview.array, frame_index=reference_frame,
                                                channel=reference_channel, z_index=z_index)

        def scaled(plane):
            low, high = np.percentile(plane, (1, 99))
            return np.clip((plane.astype(np.float32) - low) / max(float(high - low), 1.0), 0, 1)

        fixed, moving = scaled(reference), scaled(selected)
        composite = np.stack([fixed, moving, fixed], axis=-1)
        self._composite_item.setImage(composite, autoLevels=False, levels=(0, 1))
        self._composite_item.show()
        self.image_viewer.image_item.hide()
        self.lut_controls.setEnabled(False)

    @Slot()
    def _run_preview(self) -> None:
        if self._thread is not None:
            self._thread.requestInterruption()
            self.status_label.setText("Cancelling registration preview…")
            return
        if self._session is None:
            return
        try:
            settings, upstream = self.current_settings(), self._upstream()
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        self._thread = QThread(self)
        self._worker = RegistrationPreviewWorker(self._session, self.mode(), settings, upstream)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.ready.connect(self._preview_ready)
        self._worker.failed.connect(lambda message: self.status_label.setText(f"Registration preview failed: {message}"))
        self._worker.progress.connect(self._preview_progress)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._thread_finished)
        self.progress.show()
        self.image_viewer.set_preview_loading(True, "Preparing registration preview…")
        self.directory_browser.setEnabled(False)
        self.directory_edit.setEnabled(False)
        self.browse_button.setEnabled(False)
        self._settings_edited()
        self._thread.start()

    @Slot(str, int, int)
    def _preview_progress(self, message: str, done: int, total: int) -> None:
        self.status_label.setText(message)
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.image_viewer.set_preview_loading(True, message)

    @Slot(object)
    def _preview_ready(self, preview: RegistrationPreview) -> None:
        self.status_label.setText("Preview ready. Save current settings to accept it.")
        self._display_selection()

    @Slot()
    def _thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.deleteLater()
        self.progress.hide()
        self.image_viewer.set_preview_loading(False)
        self.directory_browser.setEnabled(True)
        self.directory_edit.setEnabled(True)
        self.browse_button.setEnabled(True)
        if self._closing:
            self.close()
        else:
            self._settings_edited()

    @Slot()
    def _save_settings(self) -> None:
        if self._session is None or self._thread is not None:
            return
        try:
            settings = self.current_settings()
            preview = self._session.cached_preview(self.mode(), settings, self._upstream())
            if preview is None:
                raise ValueError("Run a preview with these settings before saving.")
            if self._general_adapter is not None and self._general_path is not None:
                step = StepName.REGISTER_TIME if self.mode() == "time" else StepName.REGISTER_CHANNEL
                for key, value in {**settings.to_payload_dict(), "overwrite": settings.overwrite}.items():
                    self._general_adapter.set_field_value(step, key, "None" if value is None else value)
                self._general_adapter.save(self._general_path)
            path = self._session.save_preview(preview)
            self._defaults[self.mode()] = settings.model_copy(deep=True)
            self.settings_applied.emit(self.mode(), settings)
            self.status_label.setText(f"Saved general {self.mode()} settings and tuned transforms: {path}")
        except Exception as error:
            self.status_label.setText(f"Cannot save registration tuning: {error}")

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if event.key() == Qt.Key.Key_R:
            self._run_preview()
            return True
        if event.key() == Qt.Key.Key_S:
            self._save_settings()
            return True
        if event.key() == Qt.Key.Key_X:
            self.comparison.setCurrentIndex(1 if self.comparison.currentIndex() != 1 else 0)
            return True
        return False

    def _clear_tools(self) -> None:
        self._composite_item.clear()
        self._composite_item.hide()
        self.image_viewer.image_item.show()
        self._session = None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            self._closing = True
            self._thread.requestInterruption()
            self.status_label.setText("Cancelling registration preview…")
            event.ignore()
            return
        super().closeEvent(event)
