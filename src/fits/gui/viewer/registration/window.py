"""Time/channel registration tuning in one standard FITS image viewer."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, QSignalBlocker, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

from fits.gui.settings.wheel_widgets import FocusWheelComboBox
from fits.environment.constant import FITS_ARRAY_NAME, StepName
from fits.gui.settings import SettingsAdapter
from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.common.crop import CropPanel
from fits.interaction.crop import CropBounds
from fits.gui.viewer.common.information_dialog import REGISTRATION_HELP
from fits.gui.viewer.registration.settings_panel import RegistrationSettingsPanel
from fits.gui.viewer.registration.worker import RegistrationPreviewWorker
from fits.settings.loader import run_settings_path
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.tuned import Mode, RegistrationSettings, load_tuning
from fits.tasks.registration.tuning import RegistrationPreview, RegistrationTuningSession


class RegistrationTunerWindow(ImageToolWindow):
    settings_applied = Signal(str, object)
    auto_open_first_image = True
    file_filters = (FITS_ARRAY_NAME,)
    help_gui = "RegTune"
    tool_help = REGISTRATION_HELP

    def __init__(self, experiments_dir: str | Path | None = None, *, mode: Mode = "time",
                 time_settings: RegisterTimeSettings | None = None,
                 channel_settings: RegisterChannelSettings | None = None,
                 settings_path: Path | None = None,
                 initial_path: str | Path | None = None,
                 parent: QWidget | None = None, directory_locked: bool = False) -> None:
        """Build the shared time/channel tuner and optionally open an experiment."""
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
        super().__init__(None, parent, directory_locked=directory_locked)
        self.tabs.setCurrentIndex(0 if mode == "time" else 1)
        self.overlay_label.hide()
        self.show_mask.hide()
        self.mask_opacity.hide()
        self.setWindowTitle("FITS Registration Tuner")
        self.resize(1500, 950)
        if experiments_dir is not None:
            self._set_experiments_directory(experiments_dir, initial_path=initial_path)

    def _build_tools(self) -> QWidget:
        """Build both settings tabs and their optional crop controls."""
        self.tool_panel = QWidget()
        layout = QVBoxLayout(self.tool_panel)
        self.tabs = QTabWidget()
        self.panels: dict[Mode, RegistrationSettingsPanel] = {
            "time": RegistrationSettingsPanel("time"), "channel": RegistrationSettingsPanel("channel")}
        self.crops: dict[Mode, CropPanel] = {}
        for mode, panel in self.panels.items():
            crop = CropPanel(automatic=False)
            crop.setMinimumHeight(crop.sizeHint().height())
            self.crops[mode] = crop
            panel.crop_layout.addWidget(crop)
        self.tabs.addTab(self.panels["time"], "Time registration")
        self.tabs.addTab(self.panels["channel"], "Channel registration")
        layout.addWidget(self.tabs, 1)
        self.run_button = QPushButton("Run preview")
        self.run_button.setToolTip(
            "Fit transforms using the selected tab's settings and enabled crop. "
            "Registered planes are applied as you navigate. "
            "Click again to cancel a running preview.")
        self.run_button.setStyleSheet(
            "QPushButton { background-color: #d97706; color: white; "
            "font-weight: bold; padding: 6px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #ea8a0c; } "
            "QPushButton:pressed { background-color: #b85f05; }")
        self.save_button = QPushButton("Save current settings")
        self.save_button.setToolTip(
            "Save settings, the enabled fitting crop and fitted transforms for the selected "
            "Time registration or Channel registration tab only. A preview is optional. "
            "Keep the viewer open to continue tuning either registration tab.")
        self.save_button.setStyleSheet(
            "QPushButton { background-color: #4f8f5b; color: white; "
            "padding: 6px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #5ca568; } "
            "QPushButton:pressed { background-color: #3f7449; }")
        self.complete_button = QPushButton("Complete session")
        self.complete_button.setToolTip(
            "Save both registration tabs, then close this viewer. Matching preview transforms "
            "are saved when available; otherwise fitting will run in the pipeline. "
            "The viewer stays open if saving fails.")
        self.complete_button.setStyleSheet(
            "QPushButton { background-color: #16803b; color: white; "
            "font-weight: bold; padding: 7px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #1c9848; } "
            "QPushButton:pressed { background-color: #11652f; }")
        return self.tool_panel

    def _build_viewer_actions(self, layout: QHBoxLayout) -> None:
        """Place the registration actions to the right of the LUT."""
        self.session_actions = QWidget()
        actions_layout = QVBoxLayout(self.session_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        for button in (self.run_button, self.save_button, self.complete_button):
            actions_layout.addWidget(button)
        layout.addStretch(1)
        layout.addWidget(self.session_actions)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep both resolved cards aligned when the settings area is resized."""
        if isinstance(watched, RegistrationSettingsPanel) and event.type() == QEvent.Type.Resize:
            self._sync_resolved_panel_heights()
        return super().eventFilter(watched, event)

    def _sync_resolved_panel_heights(self) -> None:
        """Reserve the same wrapped-summary height in both registration tabs."""
        panel = self.panels[self.mode()]
        layout = panel.layout()
        assert layout is not None
        margins = layout.contentsMargins()
        width = max(1, panel.width() - margins.left() - margins.right())
        heights = []
        for candidate in self.panels.values():
            summary_layout = candidate.resolved_group.layout()
            assert summary_layout is not None
            heights.append(summary_layout.totalHeightForWidth(width))
        height = max(heights)
        if height > 0:
            for candidate in self.panels.values():
                candidate.resolved_group.setFixedHeight(height)

    def _set_source_controls_enabled(self, enabled: bool) -> None:
        """Enable source navigation and registration actions together."""
        super()._set_source_controls_enabled(enabled)
        self.session_actions.setEnabled(enabled)

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        """Build the image comparison menu with per-item explanations."""
        self.comparison = FocusWheelComboBox()
        options = (
            ("Registered image", "Show the selected image after registration using a matching "
             "completed preview. Shows the original image until a matching preview is available."),
            ("Original image", "Show the original image before registration for comparison."),
            ("Composite overlay", "Overlay the original and registered images at the same frame, "
             "channel and Z plane to show how registration moved the image. The original is "
             "grayscale and the registered image uses the selected channel LUT. If that LUT is "
             "grayscale, the original is magenta instead. Each image is auto-scaled separately "
             "for comparison. Requires a matching completed preview."),
        )
        for label, tooltip in options:
            self.comparison.addItem(label)
            self.comparison.setItemData(
                self.comparison.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole)
        self.comparison.setToolTip(options[0][1])
        self.comparison.currentIndexChanged.connect(
            lambda index: self.comparison.setToolTip(
                self.comparison.itemData(index, Qt.ItemDataRole.ToolTipRole)))
        layout.addWidget(self.comparison)

    def _connect_tools(self) -> None:
        """Connect registration actions, crop tools and display controls."""
        self._composite_item = pg.ImageItem(axisOrder="row-major")
        self._composite_item.setZValue(1)
        self.image_viewer.view_box.addItem(self._composite_item)
        self._composite_item.hide()
        for mode, crop in self.crops.items():
            crop.bind(self.image_viewer)
            crop.set_active(mode == self.mode())
            crop.changed.connect(self._settings_edited)
        self.run_button.clicked.connect(self._run_preview)
        self.save_button.clicked.connect(self._save_settings)
        self.complete_button.clicked.connect(self._complete_session)
        self.tabs.currentChanged.connect(self._settings_edited)
        self.channel_combo.currentIndexChanged.connect(self._display_channel_changed)
        self.comparison.currentIndexChanged.connect(self._display_selection)
        self.grayscale_lut_button.toggled.connect(self._display_selection)
        self.image_viewer.histogram.item.gradient.sigGradientChanged.connect(self._composite_lut_changed)
        for panel in self.panels.values():
            panel.changed.connect(self._settings_edited)

    def mode(self) -> Mode:
        """Return the selected registration tab."""
        return "time" if self.tabs.currentIndex() == 0 else "channel"

    def current_settings(self) -> RegistrationSettings:
        """Read validated settings from the selected tab."""
        return self.panels[self.mode()].settings()

    @Slot(int)
    def _display_channel_changed(self, index: int) -> None:
        """Use explicit display-channel choices in the active registration settings."""
        if not self._loading and self._session is not None and index >= 0:
            self.panels[self.mode()].channel.setCurrentIndex(index)

    def _composite_lut_changed(self) -> None:
        """Refresh the composite after LUT edits, once channel colour updates finish."""
        if self.comparison.currentIndex() == 2:
            QTimer.singleShot(0, self._display_selection)

    def _crop(self, mode: Mode | None = None) -> CropBounds | None:
        """Use a tab's stored rectangle only while its crop tool is enabled."""
        crop = self.crops[mode or self.mode()]
        return crop.bounds if crop.enabled.isChecked() else None

    def _general_settings(self, source: Path) -> None:
        """Load general registration defaults for the selected experiment."""
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
        self._general_adapter = adapter
        self._general_path = path or run_settings_path(root)

    @Slot(object)
    def _path_selected(self, selected: object) -> None:
        """Open the selected normalized image or experiment directory."""
        if isinstance(selected, (str, Path)):
            source = Path(selected)
            self._open_source(source / FITS_ARRAY_NAME if source.is_dir() else source)

    def _open_source(self, source: Path) -> None:
        """Load one experiment and reset preview and crop controls."""
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
                panel.load(self._defaults[mode] if self._provided or tuned is None else tuned.settings,
                           session.channel_labels, session.frame_count)
                self.crops[mode].reset((session._axis_size("Y"), session._axis_size("X")))
                if tuned is not None and tuned.crop is not None:
                    self.crops[mode].set_bounds(tuned.crop)
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
        """Refresh preview validity, actions and the displayed image."""
        if self._loading:
            return
        for mode, crop in self.crops.items():
            if mode != self.mode():
                crop.set_active(False)
            crop.set_busy(self._thread is not None)
        self.crops[self.mode()].set_active(True)
        for mode, panel in self.panels.items():
            panel.update_resolved(crop_active=self._crop(mode) is not None)
        self._sync_resolved_panel_heights()
        valid = False
        if self._session is not None:
            if self.mode() != self._last_mode:
                self._last_mode = self.mode()
                channel = self.panels[self.mode()].channel.currentIndex()
                if self.mode() == "channel":
                    channel = next((i for i in range(self.channel_combo.count()) if i != channel), 0)
                with QSignalBlocker(self.channel_combo):
                    self.channel_combo.setCurrentIndex(channel)
                self.comparison.setCurrentIndex(2 if self.mode() == "channel" else 0)
            try:
                settings = self.current_settings()
                valid = True
            except Exception as error:
                self.panels[self.mode()].resolved.setText(str(error))
        self.run_button.setText("Cancel preview" if self._thread is not None else "Run preview")
        self.run_button.setEnabled(valid or self._thread is not None)
        self.save_button.setEnabled(valid and self._thread is None)
        self.complete_button.setEnabled(self._session is not None and self._thread is None)
        self._display_selection()

    def _display_overlay(self, image, frame, channel, z_index) -> None:
        """Display one original, registered or composite plane on demand."""
        self._composite_item.hide()
        self.image_viewer.image_item.show()
        self.lut_controls.setEnabled(True)
        if self._session is None or self._loading:
            return
        try:
            settings = self.current_settings()
            preview = self._session.cached_preview(self.mode(), settings,
                                                    crop=self._crop())
        except ValueError:
            return
        if preview is None or self.comparison.currentIndex() == 1:
            return
        selected = self._session.preview_frame(preview, frame, channel, z_index)
        self.image_viewer.set_image(selected)
        if self.comparison.currentIndex() != 2:
            return
        def scaled(plane):
            """Normalize image contrast for an alignment comparison."""
            low, high = np.percentile(plane, (1, 99))
            return np.clip((plane.astype(np.float32) - low) / max(float(high - low), 1.0), 0, 1)

        original, registered = scaled(image), scaled(selected)
        colour_map = self.image_viewer.histogram.item.gradient.colorMap()
        palette = np.asarray(colour_map.getLookupTable(nPts=256, alpha=False, mode=pg.ColorMap.FLOAT), dtype=np.float32)
        grayscale = (self.grayscale_lut_button.isChecked()
                     or (np.allclose(palette[:, 0], palette[:, 1]) and np.allclose(palette[:, 1], palette[:, 2])))
        original_colour = np.array((1, 0, 1) if grayscale else (1, 1, 1), dtype=np.float32)
        background = original[..., None] * original_colour
        foreground = (np.repeat(registered[..., None], 3, axis=-1) if self.grayscale_lut_button.isChecked()
                      else np.asarray(colour_map.map(registered, mode=pg.ColorMap.FLOAT), dtype=np.float32)[..., :3])
        # Screen blending retains either image where the other has no signal.
        composite = 1 - (1 - background) * (1 - foreground)
        self._composite_item.setImage(composite, autoLevels=False, levels=(0, 1))
        self._composite_item.show()
        self.image_viewer.image_item.hide()
        self.lut_controls.setEnabled(False)

    @Slot()
    def _run_preview(self) -> None:
        """Start or cancel a background registration fit."""
        if self._thread is not None:
            self._thread.requestInterruption()
            self.status_label.setText("Cancelling registration preview…")
            return
        if self._session is None:
            return
        try:
            settings = self.current_settings()
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        self._thread = QThread(self)
        self._worker = RegistrationPreviewWorker(self._session, self.mode(), settings,
                                                  crop=self._crop())
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
        self._set_directory_controls_enabled(False)
        self._settings_edited()
        self._thread.start()

    @Slot(str, int, int)
    def _preview_progress(self, message: str, done: int, total: int) -> None:
        """Show fitting progress without applying the complete stack."""
        self.status_label.setText(message)
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.image_viewer.set_preview_loading(True, message)

    @Slot(object)
    def _preview_ready(self, preview: RegistrationPreview) -> None:
        """Show the first requested plane after transforms are fitted."""
        self.status_label.setText("Transforms ready. Preview applies as you navigate; save settings to accept them.")
        self._display_selection()

    @Slot()
    def _thread_finished(self) -> None:
        """Restore controls after a fit finishes or is cancelled."""
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.deleteLater()
        self.progress.hide()
        self.image_viewer.set_preview_loading(False)
        self.directory_browser.setEnabled(True)
        self._set_directory_controls_enabled(True)
        if self._closing:
            self.close()
        else:
            self._settings_edited()

    @Slot()
    def _save_settings(self) -> None:
        """Save current settings and crop, including matching transforms when available."""
        if self._session is None or self._thread is not None:
            return
        try:
            settings = self.current_settings()
            preview = self._session.cached_preview(self.mode(), settings,
                                                    crop=self._crop())
            self._save_tab(self.mode(), settings, preview)
        except Exception as error:
            self.status_label.setText(f"Cannot save registration tuning: {error}")

    def _save_tab(self, mode: Mode, settings: RegistrationSettings,
                  preview: RegistrationPreview | None) -> None:
        """Persist one tab with optional transforms and notify the main GUI."""
        assert self._session is not None
        if self._general_adapter is not None and self._general_path is not None:
            step = StepName.REGISTER_TIME if mode == "time" else StepName.REGISTER_CHANNEL
            for key, value in {**settings.to_payload_dict(), "overwrite": settings.overwrite}.items():
                self._general_adapter.set_field_value(step, key, "None" if value is None else value)
            self._general_adapter.save(self._general_path)
        path = (self._session.save_preview(preview) if preview is not None else
                self._session.save_settings(settings, crop=self._crop(mode)))
        self._defaults[mode] = settings.model_copy(deep=True)
        self.settings_applied.emit(mode, settings)
        detail = "settings and fitted transforms" if preview is not None else "settings; fitting will run in the pipeline"
        self.status_label.setText(f"Saved {mode} {detail}: {path}")

    @Slot()
    def _complete_session(self) -> None:
        """Save both tabs with optional matching transforms and close after success."""
        if self._session is None or self._thread is not None:
            return
        try:
            settings_by_mode: dict[Mode, RegistrationSettings] = {mode: panel.settings() for mode, panel in self.panels.items()}
            for mode, settings in settings_by_mode.items():
                preview = self._session.cached_preview(mode, settings, crop=self._crop(mode))
                self._save_tab(mode, settings, preview)
        except Exception as error:
            self.status_label.setText(f"Cannot save registration tuning: {error}")
            return
        self.close()

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        """Handle registration preview, save and comparison shortcuts."""
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
        """Clear registration overlays, crop controls and the session reference."""
        self._session = None
        for crop in self.crops.values():
            with QSignalBlocker(crop):
                crop.reset()
        self._composite_item.clear()
        self._composite_item.hide()
        self.image_viewer.image_item.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Cancel active fitting before closing the viewer."""
        if self._thread is not None:
            self._closing = True
            self._thread.requestInterruption()
            self.status_label.setText("Cancelling registration preview…")
            event.ignore()
            return
        super().closeEvent(event)
