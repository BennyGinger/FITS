"""Background-subtraction tuning using the shared FIScH image viewer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from fisch.environment import constant as cst
import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget
from fisch.workflows.artifacts.paths import image_input_for, image_for, first_image
from fisch.environment.constant import IMAGE_NAMES, ARRAY_NAME, StepName
from fisch.gui.settings import SettingsAdapter
from fisch.gui.settings.wheel_widgets import FocusWheelComboBox
from fisch.gui.viewer.background.settings_panel import BackgroundSettingsPanel
from fisch.gui.viewer.background.worker import BackgroundPreviewWorker
from fisch.gui.viewer.common.base_window import ImageToolWindow
from fisch.gui.viewer.common.area_measurement import AreaMeasurement
from fisch.gui.viewer.common.information_dialog import BACKGROUND_HELP
from fisch.gui.viewer.common.tuner_actions import CLOSE_WINDOW_STYLE, MAIN_GUI_SETTINGS_HINT, RUN_PREVIEW_STYLE, SAVE_SETTINGS_STYLE, configure_tuner_window, confirm_discard_tuner_changes, set_preview_choices, toggle_preview_choice
from fisch.settings.loader import run_settings_path
from fisch.settings.models import BGSubSettings
from fisch.tasks.bg_sub_tuning import BackgroundTuningSession


class BackgroundTunerWindow(ImageToolWindow):
    """Preview requested planes and save general settings without modifying images."""

    settings_applied = Signal(object)
    auto_open_first_image = True
    initial_panel_sizes = (380, 1170)
    initial_left_width = 460
    file_filters = IMAGE_NAMES
    help_gui = "BGTune"
    tool_help = BACKGROUND_HELP

    def __init__(self,
                 experiments_dir: str | Path | None = None,
                 *,
                 settings: BGSubSettings | None = None,
                 settings_path: Path | None = None,
                 initial_path: str | Path | None = None,
                 parent: QWidget | None = None,
                 directory_locked: bool = False,
                 settings_provider: Callable[[], BGSubSettings] | None = None,
                 ) -> None:
        """
        Load GUI settings or standalone defaults and optionally open an experiment.
        """
        self._provided = settings is not None
        self._defaults = (settings or BGSubSettings()).model_copy(deep=True)
        self._settings_path = settings_path
        self._settings_provider = settings_provider
        self._used = False
        self._general_adapter: SettingsAdapter | None = None
        self._general_path: Path | None = None
        self._session: BackgroundTuningSession | None = None
        self._thread: BackgroundPreviewWorker | None = None
        self._preview_enabled = False
        self._loading = False
        self._closing = False
        super().__init__(None, parent, directory_locked=directory_locked)
        self.overlay_label.hide()
        self.show_mask.hide()
        self.mask_opacity.hide()
        self.setWindowTitle("FIScH Background Subtraction Tuner")
        configure_tuner_window(self, self.status_label)
        if self._settings_provider is not None:
            self.save_button.setToolTip(self.save_button.toolTip() + '\n\n' + MAIN_GUI_SETTINGS_HINT)
        if experiments_dir is not None:
            self._set_experiments_directory(experiments_dir, initial_path=initial_path)

    def _build_tools(self) -> QWidget:
        """
        Build parameters, measurement controls and the shared preview/save/close actions.
        """
        self.settings_panel = BackgroundSettingsPanel()
        self.tool_panel = self.settings_panel
        self.run_button = QPushButton("Run preview")
        self.run_button.setToolTip("Process the selected frame/channel/Z plane. Navigation then computes "
                                   "only requested planes. Run again after changing settings.")
        self.run_button.setStyleSheet(RUN_PREVIEW_STYLE)
        self.save_button = QPushButton("Save current settings")
        self.save_button.setToolTip("Save background-subtraction settings and keep the tuner open. Preview is optional. "
                                    "Images and the pipeline step's enabled state are unchanged.")
        self.save_button.setStyleSheet(SAVE_SETTINGS_STYLE)
        self.close_button = QPushButton("Close window")
        self.close_button.setToolTip("Close the tuner. You will be warned about unsaved background-subtraction settings.")
        self.close_button.setStyleSheet(CLOSE_WINDOW_STYLE)
        return self.settings_panel

    def _build_viewer_actions(self, layout: QHBoxLayout) -> None:
        """
        Stack the orange preview, green save and light-red close actions beside the LUT.
        """
        self.measurement = AreaMeasurement(self.image_viewer, self)
        self.settings_panel.drawing_layout.addWidget(self.measurement.drawing)
        self.measurement.profile_button.setFixedSize(self.auto_scale_button.size())
        self.measurement.profile_button.setFont(self.auto_scale_button.font())
        self.lut_profile_layout.insertWidget(0, self.measurement.profile_button)
        self.session_actions = QWidget()
        actions = QVBoxLayout(self.session_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        for button in (self.run_button, self.save_button, self.close_button):
            actions.addWidget(button)
        layout.addStretch(1)
        layout.addWidget(self.session_actions)

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        """
        Offer original and processed images with per-option help.
        """
        self.comparison = FocusWheelComboBox()
        for title, description in (
            ("Original image", "Original pixels. Press V to switch; intensity limits stay the same."),
            ("Background-subtracted image", "Processed pixels for this plane and these settings. "
             "Run preview first. Press V to switch back to the original.")):
            self.comparison.addItem(title)
            self.comparison.setItemData(self.comparison.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        self.comparison.currentIndexChanged.connect(self._comparison_changed)
        set_preview_choices(self.comparison, False, 0)
        self._comparison_changed()
        layout.addWidget(self.comparison)

    def _comparison_changed(self) -> None:
        """
        Update comparison help; display refresh is connected after UI creation.
        """
        self.comparison.setToolTip(self.comparison.currentData(Qt.ItemDataRole.ToolTipRole))

    def _connect_tools(self) -> None:
        """
        Connect processing actions, settings and image comparison controls.
        """
        self.settings_panel.changed.connect(self._settings_edited)
        self.run_button.clicked.connect(self._run_preview)
        self.save_button.clicked.connect(self._save_settings)
        self.close_button.clicked.connect(self.close)
        self.comparison.currentIndexChanged.connect(self._display_selection)

    def _set_source_controls_enabled(self, enabled: bool) -> None:
        """
        Enable tuning and navigation when an experiment is open.
        """
        super()._set_source_controls_enabled(enabled)
        self.session_actions.setEnabled(enabled)

    def _load_general_settings(self, source: Path) -> None:
        """
        Find standalone settings without overriding settings passed by the GUI.
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
        self._defaults = BGSubSettings.model_validate(adapter.as_mapping()["bg_sub"]["params"])
        self._general_adapter = adapter
        self._general_path = path or run_settings_path(root)

    @Slot(object)
    def _path_selected(self, selected: object) -> None:
        """
        Open the chosen normalized image or its experiment directory.
        """
        if isinstance(selected, (str, Path)):
            source = Path(selected)
            self._open_source((image_for(source) or source / ARRAY_NAME) if source.is_dir() else source)

    def _open_source(self, source: Path) -> None:
        """
        Replace the input and release previews when selecting another experiment.
        """
        try:
            source = image_input_for(source, cst.StepName.BG_SUB) or source
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        if source == self._source_path:
            return
        if self._thread is not None:
            self.status_label.setText("Wait for the selected plane to finish before changing experiment.")
            return
        if source.name not in IMAGE_NAMES or not source.is_file():
            self.status_label.setText("Choose an experiment folder containing FIScH image artifacts.")
            return
        self._close_session()
        self._loading = True
        try:
            self._load_general_settings(source)
            session = BackgroundTuningSession(source)
            self._session = session
            self._image_session = session
            self._source_path = source
            self._used = False
            self.settings_panel.load(self._defaults, session.channel_labels)
            with QSignalBlocker(self.channel_combo):
                self.channel_combo.addItems(list(session.channel_labels))
            self.frame_slider.setRange(0, session.frame_count - 1)
            self.z_slider.setRange(0, session.plane_count - 1)
            self._set_source_controls_enabled(True)
            self.status_label.setText("Choose settings, then Run preview for the current plane.")
        except Exception as error:
            self._close_session()
            self.status_label.setText(str(error))
        finally:
            self._loading = False
        self._display_selection()

    def _settings_edited(self) -> None:
        """
        Hide stale processed images until the user explicitly previews new settings.
        """
        if self._loading:
            return
        self._used = True
        self._preview_enabled = False
        self.status_label.setText("Settings changed. Run preview to update the processed image.")
        self._display_selection()

    def _channel_cycle_indices(self) -> list[int]:
        """Cycle only channels included in background subtraction."""
        excluded = self.settings_panel.settings().exclude_channel or ()
        return [index for index in super()._channel_cycle_indices()
                if self.channel_combo.itemText(index) not in excluded]

    def _display_overlay(self, image: NDArray, frame: int, channel: str, z_index: int) -> None:
        """
        Show a matching processed plane or request just the current selection.
        """
        if self._loading or self._session is None:
            return
        set_preview_choices(self.comparison, self._preview_enabled, 0)
        settings = self.settings_panel.settings()
        result = (self._session.cached_preview(settings, frame, channel, z_index)
                  if self._preview_enabled else None)
        if result is not None and self.comparison.currentIndex() == 1:
            levels = self.image_viewer.display_levels
            self.image_viewer.set_image(result)
            self.image_viewer.set_display_levels(levels)
        self.measurement.update(self._session, image, frame, channel, z_index,
                                processed=result, background=settings if self._preview_enabled else None)
        if self._preview_enabled and result is None and self._thread is None and not self._closing:
            self._start_plane(image, settings, frame, channel, z_index)

    @Slot()
    def _run_preview(self) -> None:
        """
        Enable on-demand processing and request the selected plane first.
        """
        if self._session is None or self._thread is not None:
            return
        self._used = True
        self._preview_enabled = True
        set_preview_choices(self.comparison, True, 0)
        self.comparison.setCurrentIndex(1)
        self._display_selection()

    def _start_plane(self, image: NDArray, settings: BGSubSettings, frame: int, channel: str, z: int) -> None:
        """
        Run one plane in a worker; coalesce navigation into the next current plane.
        """
        assert self._session is not None
        self._thread = BackgroundPreviewWorker(self._session, image.copy(), settings, frame, channel, z, self)
        self._thread.ready.connect(self._preview_ready)
        self._thread.failed.connect(self._preview_failed)
        self._thread.finished.connect(self._thread_finished)
        self.run_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.directory_browser.setEnabled(False)
        self._set_directory_controls_enabled(False)
        self.progress.show()
        self.image_viewer.set_preview_loading(True, "Computing selected plane…")
        self.status_label.setText(f"Computing frame {frame + 1}, {channel}, Z {z + 1}…")
        self._thread.start()

    @Slot(float)
    def _preview_ready(self, seconds: float) -> None:
        """
        Report per-plane latency so users can assess interactive performance.
        """
        if self._preview_enabled and not self._closing:
            self.status_label.setText(f"Preview plane computed in {seconds:.3f} s. Press V to compare.")

    @Slot(str)
    def _preview_failed(self, message: str) -> None:
        """
        Stop automatic requests after an error, keeping source and settings usable.
        """
        self._preview_enabled = False
        self.status_label.setText(f"Background preview failed: {message}")

    @Slot()
    def _thread_finished(self) -> None:
        """
        Restore controls, then display or process the latest requested plane.
        """
        thread = self._thread
        # finished can arrive before native thread-local cleanup has completed.
        if thread is not None:
            thread.wait()
        self._thread = None
        if thread is not None:
            thread.deleteLater()
        self.progress.hide()
        self.image_viewer.set_preview_loading(False)
        self.run_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.directory_browser.setEnabled(True)
        self._set_directory_controls_enabled(True)
        if self._closing:
            self.close()
        else:
            self._display_selection()

    @Slot()
    def _save_settings(self) -> None:
        """
        Save general settings and stay open, without requiring a preview.
        """
        if not self._can_write_source():
            return
        if self._session is None or self._thread is not None:
            return
        try:
            settings = self.settings_panel.settings()
            if self._general_adapter is not None and self._general_path is not None:
                for key, value in {**settings.to_payload_dict(), "overwrite": settings.overwrite}.items():
                    self._general_adapter.set_field_value(StepName.BG_SUB,
                                                          key,
                                                          "None" if value is None else value,
                                                          )
                self._general_adapter.save(self._general_path)
            self._defaults = settings.model_copy(deep=True)
            self.settings_applied.emit(settings)
        except Exception as error:
            self.status_label.setText(f"Cannot save background settings: {error}")
            return
        self.status_label.setText("Applied background-subtraction settings to the main GUI." if self._settings_provider is not None
                                  else "Saved background-subtraction settings.")

    def _has_unsaved_settings(self) -> bool:
        """Compare processing settings with their saved values, ignoring measurement/display controls."""
        if self._session is None or not self._used:
            return False
        try:
            current = self.settings_panel.settings()
            saved = self._settings_provider() if self._settings_provider is not None else self._defaults
            def comparable(settings: BGSubSettings) -> dict:
                return {**settings.to_payload_dict(), "overwrite": settings.overwrite,
                        "exclude_channel": sorted(settings.exclude_channel or ())}
            return comparable(current) != comparable(saved)
        except ValueError:
            return True

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        """
        Run preview, save without closing, or compare source and processed images.
        """
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if event.key() == Qt.Key.Key_R:
            self._run_preview()
        elif event.key() == Qt.Key.Key_S:
            self._save_settings()
        elif event.key() == Qt.Key.Key_V:
            toggle_preview_choice(self.comparison)
        else:
            return False
        return True

    def _clear_tools(self) -> None:
        """
        Reset tool state before the shared base closes the current input.
        """
        self._preview_enabled = False
        set_preview_choices(self.comparison, False, 0)
        self._session = None
        self.measurement.reset()

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Wait for the single active SMO call before releasing its source and model.
        """
        if (not self._closing and self._has_unsaved_settings()
                and not confirm_discard_tuner_changes(self, ["Background subtraction"])):
            event.ignore()
            return
        if self._thread is not None:
            self._closing = True
            self.status_label.setText("Closing after the current plane finishes…")
            event.ignore()
            return
        super().closeEvent(event)
