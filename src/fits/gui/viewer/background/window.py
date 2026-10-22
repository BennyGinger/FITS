"""Background-subtraction tuning using the shared FITS image viewer."""

from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from fits.environment.constant import FITS_ARRAY_NAME, StepName
from fits.gui.settings import SettingsAdapter
from fits.gui.settings.wheel_widgets import FocusWheelComboBox
from fits.gui.viewer.background.settings_panel import BackgroundSettingsPanel
from fits.gui.viewer.background.worker import BackgroundPreviewWorker
from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.common.information_dialog import BACKGROUND_HELP
from fits.settings.loader import run_settings_path
from fits.settings.models import BGSubSettings
from fits.tasks.bg_sub_tuning import BackgroundTuningSession


class BackgroundTunerWindow(ImageToolWindow):
    """Preview requested planes and save general settings without modifying images."""

    settings_applied = Signal(object)
    auto_open_first_image = True
    file_filters = (FITS_ARRAY_NAME,)
    help_gui = "BGTune"
    tool_help = BACKGROUND_HELP

    def __init__(self, experiments_dir: str | Path | None = None, *,
                 settings: BGSubSettings | None = None, settings_path: Path | None = None,
                 initial_path: str | Path | None = None, parent: QWidget | None = None,
                 directory_locked: bool = False) -> None:
        """Load GUI settings or standalone defaults and optionally open an experiment."""
        self._provided = settings is not None
        self._defaults = settings or BGSubSettings()
        self._settings_path = settings_path
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
        self.setWindowTitle("FITS Background Subtraction Tuner")
        self.resize(1500, 950)
        if experiments_dir is not None:
            self._set_experiments_directory(experiments_dir, initial_path=initial_path)

    def _build_tools(self) -> QWidget:
        """Build parameters, measurement controls and the two requested actions."""
        self.settings_panel = BackgroundSettingsPanel()
        self.tool_panel = self.settings_panel
        self.run_button = QPushButton("Run preview")
        self.run_button.setToolTip("Process the selected frame/channel/Z plane. Navigation then computes "
                                   "only requested planes. Run again after changing settings.")
        self.run_button.setStyleSheet(
            "QPushButton { background-color: #d97706; color: white; font-weight: bold; "
            "padding: 7px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #ea8a0c; } "
            "QPushButton:pressed { background-color: #b85f05; }")
        self.save_button = QPushButton("Save and close")
        self.save_button.setToolTip("Save background-subtraction settings and close. Preview is optional. "
                                    "Images and the pipeline step's enabled state are unchanged.")
        self.save_button.setStyleSheet(
            "QPushButton { background-color: #16803b; color: white; font-weight: bold; "
            "padding: 7px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #1c9848; } "
            "QPushButton:pressed { background-color: #11652f; }")
        return self.settings_panel

    def _build_viewer_actions(self, layout: QHBoxLayout) -> None:
        """Place the orange and dark-green actions to the right of the LUT."""
        self.session_actions = QWidget()
        actions = QVBoxLayout(self.session_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self.run_button)
        actions.addWidget(self.save_button)
        layout.addStretch(1)
        layout.addWidget(self.session_actions)

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        """Offer original and processed images with per-option help."""
        self.comparison = FocusWheelComboBox()
        for title, description in (
            ("Original image", "Original pixels. Press V to switch; intensity limits stay the same."),
            ("Background-subtracted image", "Processed pixels for this plane and these settings. "
             "Run preview first. Press V to switch back to the original.")):
            self.comparison.addItem(title)
            self.comparison.setItemData(self.comparison.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        self.comparison.currentIndexChanged.connect(self._comparison_changed)
        self._comparison_changed()
        layout.addWidget(self.comparison)

    def _comparison_changed(self) -> None:
        """Update comparison help; display refresh is connected after UI creation."""
        self.comparison.setToolTip(self.comparison.currentData(Qt.ItemDataRole.ToolTipRole))

    def _connect_tools(self) -> None:
        """Connect actions and the shared measurement rectangle."""
        self.settings_panel.measurement.bind(self.image_viewer)
        self.settings_panel.measurement.changed.connect(self._display_selection)
        self.settings_panel.changed.connect(self._settings_edited)
        self.run_button.clicked.connect(self._run_preview)
        self.save_button.clicked.connect(self._save_and_close)
        self.comparison.currentIndexChanged.connect(self._display_selection)

    def _set_source_controls_enabled(self, enabled: bool) -> None:
        """Enable tuning and navigation when an experiment is open."""
        super()._set_source_controls_enabled(enabled)
        self.session_actions.setEnabled(enabled)

    def _load_general_settings(self, source: Path) -> None:
        """Find standalone settings without overriding settings passed by the GUI."""
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
        """Open the chosen normalized image or its experiment directory."""
        if isinstance(selected, (str, Path)):
            source = Path(selected)
            self._open_source(source / FITS_ARRAY_NAME if source.is_dir() else source)

    def _open_source(self, source: Path) -> None:
        """Replace the input and release previews when selecting another experiment."""
        if source == self._source_path:
            return
        if self._thread is not None:
            self.status_label.setText("Wait for the selected plane to finish before changing experiment.")
            return
        if source.name != FITS_ARRAY_NAME or not source.is_file():
            self.status_label.setText(f"Choose a folder containing {FITS_ARRAY_NAME}.")
            return
        self._close_session()
        self._loading = True
        try:
            self._load_general_settings(source)
            session = BackgroundTuningSession(source)
            self._session = session
            self._image_session = session
            self._source_path = source
            self.settings_panel.load(self._defaults, session.channel_labels)
            self.settings_panel.measurement.reset((session._axis_size("Y"), session._axis_size("X")))
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
        """Hide stale processed images until the user explicitly previews new settings."""
        if self._loading:
            return
        self._preview_enabled = False
        self.status_label.setText("Settings changed. Run preview to update the processed image.")
        self._display_selection()

    def _display_overlay(self, image: NDArray, frame: int, channel: str, z_index: int) -> None:
        """Show a matching processed plane or request just the current selection."""
        if self._loading or self._session is None:
            return
        settings = self.settings_panel.settings()
        result = (self._session.cached_preview(settings, frame, channel, z_index)
                  if self._preview_enabled else None)
        if result is not None and self.comparison.currentIndex() == 1:
            levels = self.image_viewer.display_levels
            self.image_viewer.set_image(result)
            self.image_viewer.set_display_levels(levels)
        self._update_means(image, result)
        if self._preview_enabled and result is None and self._thread is None and not self._closing:
            self._start_plane(image, settings, frame, channel, z_index)

    def _update_means(self, original: NDArray, processed: NDArray | None) -> None:
        """Measure identical raw pixel coordinates independently of LUT scaling."""
        box = self.settings_panel.measurement
        if not box.enabled.isChecked() or box.bounds is None:
            self.settings_panel.means.setText("Enable the measurement box and draw a rectangle.")
            return
        x0, y0, x1, y1 = box.bounds
        before = float(np.mean(original[y0:y1, x0:x1], dtype=np.float64))
        after = float(np.mean(processed[y0:y1, x0:x1], dtype=np.float64)) if processed is not None else None
        text = f"Original mean: {before:.6g}\n"
        text += (f"Processed mean: {after:.6g}\nDifference (original − processed): {before - after:.6g}"
                 if after is not None else "Processed mean: run preview or wait for the selected plane.")
        self.settings_panel.means.setText(text)

    @Slot()
    def _run_preview(self) -> None:
        """Enable on-demand processing and request the selected plane first."""
        if self._session is None or self._thread is not None:
            return
        self._preview_enabled = True
        self.comparison.setCurrentIndex(1)
        self._display_selection()

    def _start_plane(self, image: NDArray, settings: BGSubSettings,
                     frame: int, channel: str, z: int) -> None:
        """Run one plane in a worker; coalesce navigation into the next current plane."""
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
        """Report per-plane latency so users can assess interactive performance."""
        if self._preview_enabled and not self._closing:
            self.status_label.setText(f"Preview plane computed in {seconds:.3f} s. Press V to compare.")

    @Slot(str)
    def _preview_failed(self, message: str) -> None:
        """Stop automatic requests after an error, keeping source and settings usable."""
        self._preview_enabled = False
        self.status_label.setText(f"Background preview failed: {message}")

    @Slot()
    def _thread_finished(self) -> None:
        """Restore controls, then display or process the latest requested plane."""
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
    def _save_and_close(self) -> None:
        """Save general settings without requiring preview or changing step enablement."""
        if self._session is None or self._thread is not None:
            return
        try:
            settings = self.settings_panel.settings()
            if self._general_adapter is not None and self._general_path is not None:
                for key, value in {**settings.to_payload_dict(), "overwrite": settings.overwrite}.items():
                    self._general_adapter.set_field_value(StepName.BG_SUB, key, "None" if value is None else value)
                self._general_adapter.save(self._general_path)
            self.settings_applied.emit(settings)
        except Exception as error:
            self.status_label.setText(f"Cannot save background settings: {error}")
            return
        self.close()

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        """Run preview, save and close, or compare source and processed images."""
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if event.key() == Qt.Key.Key_R:
            self._run_preview()
        elif event.key() == Qt.Key.Key_S:
            self._save_and_close()
        elif event.key() == Qt.Key.Key_V:
            self.comparison.setCurrentIndex(1 - self.comparison.currentIndex())
        else:
            return False
        return True

    def _clear_tools(self) -> None:
        """Reset tool state before the shared base closes the current input."""
        self._preview_enabled = False
        self._session = None
        self.settings_panel.measurement.reset()
        self.settings_panel.means.setText("Enable the measurement box and draw a rectangle.")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Wait for the single active SMO call before releasing its source and model."""
        if self._thread is not None:
            self._closing = True
            self.status_label.setText("Closing after the current plane finishes…")
            event.ignore()
            return
        super().closeEvent(event)
