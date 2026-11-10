"""Time/channel registration tuning in one standard FITS image viewer."""

from __future__ import annotations
from collections.abc import Callable
from typing import Any
from numpy.typing import NDArray
from pathlib import Path
from fits.environment import constant as cst
import numpy as np
import pyqtgraph as pg
from scope_io.metadata.imageJ_meta import COLOR_MAP, label_display_color
from PySide6.QtCore import QEvent, QObject, QSignalBlocker, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget
from fits.gui.settings.wheel_widgets import FocusWheelComboBox
from fits.workflows.artifacts.paths import image_input_for, image_for, first_image
from fits.environment.constant import IMAGE_NAMES, FITS_ARRAY_NAME, StepName
from fits.gui.settings import SettingsAdapter
from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.common.crop import CropPanel
from fits.interaction.crop import CropBounds
from fits.gui.viewer.common.information_dialog import REGISTRATION_HELP
from fits.gui.viewer.common.tuner_actions import CLOSE_WINDOW_STYLE, MAIN_GUI_SETTINGS_HINT, RUN_PREVIEW_STYLE, SAVE_SETTINGS_STYLE, configure_tuner_window, confirm_discard_tuner_changes, set_preview_choices, toggle_preview_choice
from fits.gui.viewer.registration.settings_panel import RegistrationSettingsPanel
from fits.gui.viewer.registration.worker import RegistrationPreviewWorker
from fits.settings.loader import run_settings_path
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.tuned import Mode, RegistrationSettings, load_tuning
from fits.tasks.registration.tuning import RegistrationPreview, RegistrationTuningSession
from fits.tasks.registration.registration_resolver import resolve_registration_plan


class RegistrationTunerWindow(ImageToolWindow):
    settings_applied = Signal(str, object)
    auto_open_first_image = True
    file_filters = IMAGE_NAMES
    help_gui = "RegTune"
    tool_help = REGISTRATION_HELP

    def __init__(self,
                 experiments_dir: str | Path | None = None,
                 *,
                 mode: Mode = "time",
                 time_settings: RegisterTimeSettings | None = None,
                 channel_settings: RegisterChannelSettings | None = None,
                 settings_path: Path | None = None,
                 initial_path: str | Path | None = None,
                 parent: QWidget | None = None,
                 directory_locked: bool = False,
                 settings_provider: Callable[[Mode], RegistrationSettings] | None = None,
                 ) -> None:
        """
        Build the shared time/channel tuner and optionally open an experiment.
        """
        self._provided = time_settings is not None or channel_settings is not None
        self._defaults: dict[Mode, RegistrationSettings] = {
            "time": (time_settings or RegisterTimeSettings()).model_copy(deep=True),
            "channel": (channel_settings or RegisterChannelSettings()).model_copy(deep=True)}
        self._settings_path = settings_path
        self._settings_provider = settings_provider
        self._used_modes: set[Mode] = set()
        self._saved_crops: dict[Mode, CropBounds | None] = {}
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
        configure_tuner_window(self, self.status_label)
        if self._settings_provider is not None:
            self.save_button.setToolTip(self.save_button.toolTip() + '\n\n' + MAIN_GUI_SETTINGS_HINT)
        if experiments_dir is not None:
            self._set_experiments_directory(experiments_dir, initial_path=initial_path)

    def _build_tools(self) -> QWidget:
        """
        Build both settings tabs and their optional crop controls.
        """
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
        self.run_button.setStyleSheet(RUN_PREVIEW_STYLE)
        self.save_button = QPushButton("Save current settings")
        self.save_button.setToolTip(
            "Save settings, the enabled fitting crop and fitted transforms for the selected "
            "Time registration or Channel registration tab only. A preview is optional. "
            "Keep the viewer open to continue tuning either registration tab.")
        self.save_button.setStyleSheet(SAVE_SETTINGS_STYLE)
        self.close_button = QPushButton("Close window")
        self.close_button.setToolTip("Close the tuner. You will be warned about unsaved changes in either tab.")
        self.close_button.setStyleSheet(CLOSE_WINDOW_STYLE)
        return self.tool_panel

    def _build_viewer_actions(self, layout: QHBoxLayout) -> None:
        """
        Place the registration actions to the right of the LUT.
        """
        self.session_actions = QWidget()
        actions_layout = QVBoxLayout(self.session_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        for button in (self.run_button, self.save_button, self.close_button):
            actions_layout.addWidget(button)
        layout.addStretch(1)
        layout.addWidget(self.session_actions)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """
        Keep both resolved cards aligned when the settings area is resized.
        """
        if isinstance(watched, RegistrationSettingsPanel) and event.type() == QEvent.Type.Resize:
            self._sync_resolved_panel_heights()
        return super().eventFilter(watched, event)

    def _sync_resolved_panel_heights(self) -> None:
        """
        Reserve the same wrapped-summary height in both registration tabs.
        """
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
        """
        Enable source navigation and registration actions together.
        """
        super()._set_source_controls_enabled(enabled)
        self.session_actions.setEnabled(enabled)

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        """
        Build the image comparison menu with per-item explanations.
        """
        self.comparison = FocusWheelComboBox()
        self._comparison_mode: Mode | None = None
        self._set_comparison_mode()
        self.comparison.currentIndexChanged.connect(self._comparison_changed)
        layout.addWidget(self.comparison)

    def _set_comparison_mode(self) -> None:
        """Offer channel-pair alignment views separately from time-registration views."""
        mode = self.mode()
        if self._comparison_mode == mode:
            return
        self._comparison_mode = mode
        options = (
            ("Original alignment", "Overlay the original reference and selected comparison "
             "channel at the current frame and Z plane. Press C to cycle included comparison "
             "channels; press V to compare before and after registration."),
            ("Registered alignment", "Overlay the unchanged reference channel and the registered "
             "version of the same comparison channel. Requires a matching completed preview. "
             "Both views use the same colours and contrast. "
             "Press C to cycle included comparison channels and V to compare before/after."),
        ) if mode == "channel" else (
            ("Registered image", "Show the selected image after registration using a matching "
             "completed preview."),
            ("Original image", "Show the original image before registration for comparison."),
            ("Composite overlay", "Overlay the original and registered images at the same frame, "
             "channel and Z plane to show how registration moved the image. The original is "
             "grayscale and the registered image uses the selected channel LUT. If that LUT is "
             "grayscale, the original is magenta instead. Each image is auto-scaled separately "
             "for comparison. Requires a matching completed preview."),
        )
        with QSignalBlocker(self.comparison):
            self.comparison.clear()
            for label, tooltip in options:
                self.comparison.addItem(label)
                self.comparison.setItemData(self.comparison.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole)
            self.comparison.setCurrentIndex(0 if mode == "channel" else 1)
        set_preview_choices(self.comparison, False, 0 if mode == "channel" else 1)
        self.comparison.setToolTip(options[self.comparison.currentIndex()][1])
        self.grayscale_lut_button.setEnabled(mode == "time")

    @Slot()
    def _comparison_changed(self) -> None:
        """Keep the current view's explanation alongside its display."""
        self.comparison.setToolTip(self.comparison.currentData(Qt.ItemDataRole.ToolTipRole))
        self._display_selection()

    def _connect_tools(self) -> None:
        """
        Connect registration actions, crop tools and display controls.
        """
        self._composite_item = pg.ImageItem(axisOrder="row-major")
        self._composite_item.setZValue(1)
        self.image_viewer.view_box.addItem(self._composite_item)
        self._composite_item.hide()
        for mode, crop in self.crops.items():
            crop.bind(self.image_viewer)
            crop.set_active(mode == self.mode())
            crop.changed.connect(self._tuning_edited)
        self.run_button.clicked.connect(self._run_preview)
        self.save_button.clicked.connect(self._save_settings)
        self.close_button.clicked.connect(self.close)
        self.tabs.currentChanged.connect(self._settings_edited)
        self.panels["time"].channel.currentIndexChanged.connect(self._fitting_channel_changed)
        self.panels["channel"].channel.currentIndexChanged.connect(self._reference_channel_changed)
        self.grayscale_lut_button.toggled.connect(self._display_selection)
        self.image_viewer.histogram.item.gradient.sigGradientChanged.connect(self._composite_lut_changed)
        for panel in self.panels.values():
            panel.changed.connect(self._tuning_edited)

    @Slot()
    def _tuning_edited(self) -> None:
        """Track tabs used for tuning without treating initial loading as an edit."""
        if not self._loading:
            sender = self.sender()
            for mode in self.panels:
                if sender is self.panels[mode] or sender is self.crops[mode]:
                    self._used_modes.add(mode)
        self._settings_edited()

    def mode(self) -> Mode:
        """
        Return the selected registration tab.
        """
        return "time" if self.tabs.currentIndex() == 0 else "channel"

    def current_settings(self) -> RegistrationSettings:
        """
        Read validated settings from the selected tab.
        """
        return self.panels[self.mode()].settings()

    @Slot(int)
    def _fitting_channel_changed(self, index: int) -> None:
        """
        Display the selected fitting channel without linking display browsing back.
        """
        if self._loading or self.mode() != "time" or self._session is None:
            return
        selected = self.channel_combo.findText(self.panels["time"].channel.itemText(index))
        if selected >= 0:
            self.channel_combo.setCurrentIndex(selected)

    @Slot(int)
    def _reference_channel_changed(self, index: int) -> None:
        """Selecting a reference also selects that display channel, in one direction."""
        if self._loading or self.mode() != "channel" or self._session is None:
            return
        selected = self.channel_combo.findText(self.panels["channel"].channel.currentText())
        if selected >= 0:
            self.channel_combo.setCurrentIndex(selected)

    def _channel_cycle_indices(self) -> list[int]:
        """Cycle all time channels, or included non-reference channel comparisons."""
        indices = super()._channel_cycle_indices()
        if self.mode() == "time":
            return indices
        panel = self.panels["channel"]
        excluded = {panel.excluded.item(i).text() for i in range(panel.excluded.count())
                    if panel.excluded.item(i).checkState() == Qt.CheckState.Checked}
        reference = panel.channel.currentText()
        return [index for index in indices
                if self.channel_combo.itemText(index) != reference
                and self.channel_combo.itemText(index) not in excluded]

    def _next_channel(self) -> None:
        """Advance from the comparison actually shown when the selector names the reference."""
        active = self._channel_cycle_indices()
        if (self.mode() == "channel" and self.channel_combo.isEnabled() and active
                and self.channel_combo.currentText() == self.panels["channel"].channel.currentText()):
            self.channel_combo.setCurrentIndex(active[1 % len(active)])
            return
        super()._next_channel()

    def _composite_lut_changed(self) -> None:
        """
        Refresh the composite after LUT edits, once channel colour updates finish.
        """
        if self.comparison.currentIndex() == 2:
            QTimer.singleShot(0, self._display_selection)

    def _crop(self, mode: Mode | None = None) -> CropBounds | None:
        """
        Use a tab's stored rectangle only while its crop tool is enabled.
        """
        crop = self.crops[mode or self.mode()]
        return crop.bounds if crop.enabled.isChecked() else None

    def _general_settings(self, source: Path) -> None:
        """
        Load general registration defaults for the selected experiment.
        """
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
        """
        Open the selected normalized image or experiment directory.
        """
        if isinstance(selected, (str, Path)):
            source = Path(selected)
            self._open_source((image_for(source) or source / FITS_ARRAY_NAME) if source.is_dir() else source)

    def _open_source(self, source: Path) -> None:
        """
        Load one experiment and reset preview and crop controls.
        """
        try:
            source = image_input_for(source,
                                     cst.StepName.REGISTER_TIME if self.mode() == "time" else cst.StepName.REGISTER_CHANNEL,
                                     ) or source
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        if source == self._source_path:
            return
        if self._thread is not None:
            self.status_label.setText("Wait for or cancel the preview before changing experiment.")
            return
        if source.name not in IMAGE_NAMES or not source.is_file():
            self.status_label.setText("Choose an experiment folder containing FITS image artifacts.")
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
            self._used_modes.clear()
            for mode, panel in self.panels.items():
                tuned = load_tuning(source, mode)
                panel.load(self._defaults[mode],
                           session.channel_labels,
                           session.frame_count,
                           )
                self.crops[mode].reset((session._axis_size("Y"), session._axis_size("X")))
                if tuned is not None and tuned.crop is not None:
                    self.crops[mode].set_bounds(tuned.crop)
                self._saved_crops[mode] = self._crop(mode)
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
        """
        Refresh preview validity, actions and the displayed image.
        """
        if self._loading:
            return
        self._set_comparison_mode()
        for mode, crop in self.crops.items():
            if mode != self.mode():
                crop.set_active(False)
            crop.set_busy(self._thread is not None)
        self.crops[self.mode()].set_active(True)
        for mode, panel in self.panels.items():
            panel.update_resolved(crop_active=self._crop(mode) is not None)
        self._sync_resolved_panel_heights()
        valid = False
        preview_available = False
        if self._session is not None:
            if self._thread is None and self.mode() != self._last_mode:
                try:
                    step = cst.StepName.REGISTER_TIME if self.mode() == "time" else cst.StepName.REGISTER_CHANNEL
                    source = image_input_for(self._session.source_path, step)
                    if source is not None and source != self._session.source_path:
                        # Switch the input cache while preserving both tabs' unsaved
                        # settings/crops. Registration outputs share the image grid.
                        session = RegistrationTuningSession(source)
                        self._session.close()
                        self._session = session
                        self._image_session = session
                        self._source_path = source
                        self.directory_browser.select_path(source)
                except ValueError as error:
                    self.status_label.setText(str(error))
                    self.run_button.setEnabled(False)
                    return
            if self.mode() != self._last_mode:
                self._last_mode = self.mode()
                channel = self.channel_combo.findText(self.panels[self.mode()].channel.currentText())
                with QSignalBlocker(self.channel_combo):
                    self.channel_combo.setCurrentIndex(max(0, channel))
                self.comparison.setCurrentIndex(1 if self.mode() == "channel" else 0)
            try:
                settings = self.current_settings()
                preview_available = self._session.cached_preview(self.mode(), settings, crop=self._crop()) is not None
                valid = True
            except Exception as error:
                self.panels[self.mode()].resolved.setText(str(error))
        self.run_button.setText("Cancel preview" if self._thread is not None else "Run preview")
        self.run_button.setEnabled(valid or self._thread is not None)
        self.save_button.setEnabled(valid and self._thread is None)
        self.close_button.setEnabled(self._session is not None)
        set_preview_choices(self.comparison, preview_available, 0 if self.mode() == "channel" else 1)
        self._display_selection()

    def _display_overlay(self, image: NDArray[Any], frame: int, channel: str, z_index: int) -> None:
        """
        Display one original, registered or composite plane on demand.
        """
        self._composite_item.hide()
        self.image_viewer.image_item.show()
        self.lut_controls.setEnabled(True)
        self._set_composite_lut_enabled(True)
        if self._session is None or self._loading:
            return
        if self.mode() == "channel":
            self._display_channel_alignment(frame, z_index)
            return
        try:
            settings = self.current_settings()
            preview = self._session.cached_preview(self.mode(), settings, crop=self._crop())
        except ValueError:
            return
        if preview is None or self.comparison.currentIndex() == 1:
            return
        selected = self._session.preview_frame(preview, frame, channel, z_index)
        self.image_viewer.set_image(selected)
        if self.comparison.currentIndex() != 2:
            return
        def scaled(plane: np.ndarray) -> np.ndarray:
            """
            Normalize image contrast for an alignment comparison.
            """
            low, high = np.percentile(plane, (1, 99))
            return np.clip((plane.astype(np.float32) - low) / max(float(high - low), 1.0), 0, 1)

        original, registered = scaled(image), scaled(selected)
        colour_map = self.image_viewer.histogram.item.gradient.colorMap()
        palette = np.asarray(colour_map.getLookupTable(nPts=256, alpha=False, mode=pg.ColorMap.FLOAT),
                             dtype=np.float32,
                             )
        grayscale = (self.grayscale_lut_button.isChecked()
                     or (np.allclose(palette[:, 0], palette[:, 1]) and np.allclose(palette[:, 1],
                                                                                   palette[:, 2],
                                                                                   )))
        original_colour = np.array((1, 0, 1) if grayscale else (1, 1, 1), dtype=np.float32)
        background = original[..., None] * original_colour
        foreground = (np.repeat(registered[..., None], 3, axis=-1) if self.grayscale_lut_button.isChecked()
                      else np.asarray(colour_map.map(registered, mode=pg.ColorMap.FLOAT), dtype=np.float32)[..., :3])
        # Screen blending retains either image where the other has no signal.
        composite = 1 - (1 - background) * (1 - foreground)
        self._composite_item.setImage(composite, autoLevels=False, levels=(0, 1))
        self._composite_item.show()
        self.image_viewer.image_item.hide()
        self.image_viewer.pixel_readout.set_planes(((f"Original {channel}", image),
                                                   (f"Registered {channel}", selected),
                                                   ))
        self._set_composite_lut_enabled(False)

    def _set_composite_lut_enabled(self, enabled: bool) -> None:
        """
        Disable contrast editing for composites while keeping hover values readable.
        """
        self.image_viewer.histogram.setEnabled(enabled)
        self.auto_scale_button.setEnabled(enabled)
        self.full_range_button.setEnabled(enabled)

    def _display_channel_alignment(self, frame: int, z_index: int) -> None:
        """Compare a fixed pair of channels before and after channel registration."""
        assert self._session is not None
        settings = self.panels["channel"].settings()
        assert isinstance(settings, RegisterChannelSettings)
        reference = self.panels["channel"].channel.currentText()
        selected = self.channel_combo.currentText()
        if selected in (settings.exclude_channel or ()) and selected != reference:
            self.comparison.setToolTip(f"{selected} is excluded from registration and is shown unchanged.")
            return
        comparison = (selected if selected != reference else
                      next((label for label in self._session.channel_labels
                            if label != reference and label not in (settings.exclude_channel or ())), None))
        if comparison is None:
            self.image_viewer.set_image(self._session.display_frame(frame, reference, z_index))
            self.comparison.setToolTip("No other included channel is available to compare with the reference.")
            return
        original_reference = self._session.display_frame(frame, reference, z_index)
        original_comparison = self._session.display_frame(frame, comparison, z_index)
        registered = original_comparison
        preview = self._session.cached_preview("channel", settings, crop=self._crop())
        if self.comparison.currentIndex() == 1 and preview is not None:
            registered = self._session.preview_frame(preview, frame, comparison, z_index)

        def scaled(plane: np.ndarray, original: np.ndarray) -> np.ndarray:
            """Use the original plane's contrast for both alignment views."""
            low, high = np.percentile(original, (1, 99))
            return np.clip((plane.astype(np.float32) - low) / max(float(high - low), 1.0), 0, 1)

        reference_colour = label_display_color(reference)
        comparison_colour = label_display_color(comparison)
        if reference_colour in (None, "gray") or comparison_colour in (None, "gray") or reference_colour == comparison_colour:
            reference_colour, comparison_colour = "magenta", "green"
        background = scaled(original_reference, original_reference)[..., None] * np.asarray(COLOR_MAP[reference_colour])
        foreground = scaled(registered, original_comparison)[..., None] * np.asarray(COLOR_MAP[comparison_colour])
        composite = 1 - (1 - background) * (1 - foreground)
        self._composite_item.setImage(composite, autoLevels=False, levels=(0, 1))
        self._composite_item.show()
        self.image_viewer.image_item.hide()
        self.image_viewer.pixel_readout.set_planes(((reference, original_reference), (comparison, registered)))
        self._set_composite_lut_enabled(False)
        detail = f"Reference: {reference} ({reference_colour}); comparison: {comparison} ({comparison_colour})."
        if self.comparison.currentIndex() == 1 and preview is None:
            detail += " Showing original alignment; run preview for these settings to see registered alignment."
        self.comparison.setToolTip(detail)

    @Slot()
    def _run_preview(self) -> None:
        """
        Start or cancel a background registration fit.
        """
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
        self._used_modes.add(self.mode())
        self._thread = QThread(self)
        self._worker = RegistrationPreviewWorker(self._session, self.mode(), settings, crop=self._crop())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.ready.connect(self._preview_ready)
        self._worker.failed.connect(lambda message: self.status_label.setText(f"Registration preview failed: {message}"))
        self._worker.progress.connect(self._preview_progress)
        self._thread.finished.connect(self._worker.deleteLater)
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
        """
        Show fitting progress without applying the complete stack.
        """
        self.status_label.setText(message)
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.image_viewer.set_preview_loading(True, message)

    @Slot(object)
    def _preview_ready(self, preview: RegistrationPreview) -> None:
        """
        Show the first requested plane after transforms are fitted.
        """
        self._settings_edited()
        self.comparison.setCurrentIndex(1 if self.mode() == "channel" else 0)
        self.status_label.setText("Transforms ready. Preview applies as you navigate; save settings to accept them.")
        self._display_selection()

    @Slot()
    def _thread_finished(self) -> None:
        """
        Restore controls after a fit finishes or is cancelled.
        """
        thread = self._thread
        if thread is not None:
            # finished can arrive before Qt completes worker destruction.
            thread.wait()
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
        """
        Save current settings and crop, including matching transforms when available.
        """
        if self._session is None or self._thread is not None:
            return
        try:
            settings = self.current_settings()
            preview = self._session.cached_preview(self.mode(), settings, crop=self._crop())
            self._save_tab(self.mode(), settings, preview)
        except Exception as error:
            self.status_label.setText(f"Cannot save registration tuning: {error}")

    def _save_tab(self,
                  mode: Mode,
                  settings: RegistrationSettings,
                  preview: RegistrationPreview | None,
                  ) -> None:
        """
        Persist one tab with optional transforms and notify the main GUI.
        """
        assert self._session is not None
        if self._general_adapter is not None and self._general_path is not None:
            step = StepName.REGISTER_TIME if mode == "time" else StepName.REGISTER_CHANNEL
            for key, value in {**settings.to_payload_dict(), "overwrite": settings.overwrite}.items():
                self._general_adapter.set_field_value(step, key, "None" if value is None else value)
            self._general_adapter.save(self._general_path)
        path = (self._session.save_preview(preview) if preview is not None else
                self._session.save_settings(settings, crop=self._crop(mode)))
        self._defaults[mode] = settings.model_copy(deep=True)
        self._saved_crops[mode] = self._crop(mode)
        self.settings_applied.emit(mode, settings)
        detail = "settings and transforms" if preview is not None else "settings"
        self.status_label.setText(f"Applied {mode} registration settings to the main GUI."
                                  if self._settings_provider is not None else f"Saved {mode} registration {detail}.")
        self.status_label.setToolTip(str(path))

    def _comparable_settings(self, settings: RegistrationSettings) -> dict[str, Any]:
        """Compare effective choices, resolving presets and channel indices to labels."""
        plan = resolve_registration_plan(settings.context, settings.algorithm, settings.method)
        payload = {**settings.to_payload_dict(), "overwrite": settings.overwrite}
        payload.pop("context")
        payload.update(algorithm=plan.algorithm, method=plan.method)
        key = "fit_channel" if isinstance(settings, RegisterTimeSettings) else "reference_channel"
        channel = payload[key]
        if isinstance(channel, int) and self._session is not None:
            labels = self._session.channel_labels
            if 0 <= channel < len(labels):
                payload[key] = labels[channel]
        return payload

    def _unsaved_tabs(self) -> list[str]:
        """Check used tabs against main-GUI settings and their last saved crops."""
        if self._session is None:
            return []
        changed = []
        for mode in self.panels:
            if mode not in self._used_modes:
                continue
            try:
                saved = self._settings_provider(mode) if self._settings_provider is not None else self._defaults[mode]
                differs = (self._comparable_settings(self.panels[mode].settings()) != self._comparable_settings(saved)
                           or self._crop(mode) != self._saved_crops.get(mode))
            except ValueError:
                differs = True
            if differs:
                changed.append("Time registration" if mode == "time" else "Channel registration")
        return changed

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        """
        Handle registration preview, save and comparison shortcuts.
        """
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if event.key() == Qt.Key.Key_R:
            self._run_preview()
            return True
        if event.key() == Qt.Key.Key_S:
            self._save_settings()
            return True
        if event.key() == Qt.Key.Key_V:
            toggle_preview_choice(self.comparison)
            return True
        return False

    def _clear_tools(self) -> None:
        """
        Clear registration overlays, crop controls and the session reference.
        """
        self._session = None
        set_preview_choices(self.comparison, False, 0 if self.mode() == "channel" else 1)
        for crop in self.crops.values():
            with QSignalBlocker(crop):
                crop.reset()
        self._composite_item.clear()
        self._composite_item.hide()
        self.image_viewer.image_item.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Cancel active fitting before closing the viewer.
        """
        changed = self._unsaved_tabs()
        if changed and not self._closing and not confirm_discard_tuner_changes(self, changed):
            event.ignore()
            return
        if self._thread is not None:
            self._closing = True
            self._thread.requestInterruption()
            self.status_label.setText("Cancelling registration preview…")
            event.ignore()
            return
        super().closeEvent(event)
