from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from fits.environment.constant import FITS_ARRAY_NAME
from fits.gui.settings_adapter import SAVED_SETTINGS_NAME, SettingsAdapter
from fits.gui.viewer.base_window import ImageToolWindow
from fits.gui.viewer.tools.segmentation.settings_panel import CellposeSettingsPanel
from fits.gui.viewer.tools.segmentation.worker import (
    ModelInitializationRequest,
    ModelInitializationWorker,
    PreviewOutcome,
    PreviewRequest,
    PreviewWorker,
)
from fits.settings.models import SegmentSettings
from fits.tasks.segmentation.preview_cache import SegmentationPreview
from fits.tasks.segmentation.tuning import SegmentationTuningSession


class SegmentationTunerWindow(ImageToolWindow):
    """Preview segmentation and apply validated settings back to FITS."""

    settings_applied = Signal(object)
    file_filters = (FITS_ARRAY_NAME,)
    tool_help = "R    Run preview\nS    Apply segmentation settings\n"

    def __init__(self, experiments_dir: str | Path | None = None,
                 segment_settings: SegmentSettings | Mapping[str, Any] | None = None,
                 parent: QWidget | None = None, close_on_apply: bool = False) -> None:
        self._provided_settings = (SegmentSettings.model_validate(segment_settings)
                                   if segment_settings is not None else None)
        self._close_on_apply = close_on_apply
        self._segmentation_session: SegmentationTuningSession | None = None
        self._thread: QThread | None = None
        self._worker: PreviewWorker | ModelInitializationWorker | None = None
        self._active_request: PreviewRequest | None = None
        self._active_operation: str | None = None
        self._pending_model_settings: SegmentSettings | None = None
        super().__init__(experiments_dir, parent)
        self._model_change_timer = QTimer(self)
        self._model_change_timer.setSingleShot(True)
        self._model_change_timer.setInterval(300)
        self._model_change_timer.timeout.connect(self._initialize_selected_model)
        self.settings_panel.model_settings_changed.connect(
            self._model_change_timer.start)
        self.setWindowTitle("FITS Segmentation Tuner")
        if close_on_apply:
            self.settings_panel.apply_button.setText("Apply and close")

    def _build_tools(self) -> QWidget:
        self.settings_panel = CellposeSettingsPanel()
        self.settings_panel.overlay_widget.hide()
        self.tool_panel = self.settings_panel
        return self.tool_panel

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        self.segmentation_mask_colours = QLabel("Label palette")
        layout.addWidget(self.segmentation_mask_colours)

    def _connect_tools(self) -> None:
        self.settings_panel.run_requested.connect(self._run_preview)
        self.settings_panel.apply_requested.connect(self._apply_settings)
        self.settings_panel.mask_visibility_changed.connect(self.image_viewer.set_mask_visible)
        self.settings_panel.mask_opacity_changed.connect(self.image_viewer.set_mask_opacity)

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        if event.modifiers() not in (Qt.KeyboardModifier.NoModifier,
                                     Qt.KeyboardModifier.ShiftModifier):
            return False
        if event.key() == Qt.Key.Key_R:
            self._run_preview()
            return True
        if event.key() == Qt.Key.Key_S:
            self._apply_settings()
            return True
        return False

    @Slot(object)
    def _path_selected(self, selected: object) -> None:
        if not isinstance(selected, (str, Path)):
            return
        source = Path(selected)
        if source.is_dir():
            source = source / FITS_ARRAY_NAME
            if source.is_file() and self.directory_browser.select_path(source):
                return
        if source.name != FITS_ARRAY_NAME or not source.is_file():
            self.status_label.setText(f"Select an experiment containing {FITS_ARRAY_NAME}.")
            return
        self._open_source(source)

    def _open_source(self, source: Path) -> None:
        if source == self._source_path:
            return
        if self._thread is not None:
            self.status_label.setText("Wait for the current preview before changing experiment.")
            return
        self._close_session()
        try:
            baseline = self._settings_for_source(source)
            self._segmentation_session = SegmentationTuningSession(
                source, segment_settings=baseline)
        except Exception as error:
            if self._segmentation_session is not None:
                self._segmentation_session.close()
            self._segmentation_session = None
            self.status_label.setText(str(error))
            return
        self._source_path = source
        self._image_session = self._segmentation_session
        settings = self._segmentation_session.segment_settings
        self.settings_panel.set_settings(settings)
        self.settings_panel.set_channels(
            self._segmentation_session.channel_labels, settings.nuclear_channel)
        self.settings_panel.set_3d_available(
            self._segmentation_session.plane_count > 1)
        self.channel_combo.clear()
        self.channel_combo.addItems(self._segmentation_session.channel_labels)
        selected_channel = settings.channel_to_segment[0] if settings.channel_to_segment else None
        channel_index = self.channel_combo.findText(str(selected_channel))
        self.channel_combo.setCurrentIndex(max(channel_index, 0))
        self.frame_slider.setRange(0, self._segmentation_session.frame_count - 1)
        self.z_slider.setRange(0, self._segmentation_session.plane_count - 1)
        self.frame_slider.setValue(0)
        self.z_slider.setValue(0)
        self._set_source_controls_enabled(True)
        self._display_selection()
        self.status_label.setText(
            f"Loaded {source.parent.name} — axes "
            f"{self._segmentation_session.axes}, shape {self._segmentation_session.shape}.")
        self._model_change_timer.stop()
        self._initialize_selected_model()

    def _settings_for_source(self, source: Path) -> SegmentSettings | None:
        if self._provided_settings is not None:
            return self._provided_settings
        root = self.directory_browser.root_path
        for directory in (source.parent, *source.parents):
            settings_path = directory / SAVED_SETTINGS_NAME
            if settings_path.is_file():
                adapter = SettingsAdapter()
                adapter.load(settings_path)
                params = adapter.as_mapping()["segment"]["params"]
                return SegmentSettings.model_validate(params)
            if root is not None and directory == root:
                break
        return None

    def _display_overlay(self, image, frame, channel, z_index) -> None:
        self.image_viewer.set_drawing_enabled(False)
        if self._segmentation_session is None:
            return
        settings = self.current_settings()
        self._segmentation_session.set_segment_settings(settings)
        cached = self._segmentation_session.load_cached_preview(
            frame, channel, z_index, self.settings_panel.user_settings())
        if cached is not None:
            self._display_preview_mask(cached, z_index)

    def _clear_tools(self) -> None:
        if self._segmentation_session is not None:
            self._segmentation_session.close()
        self._segmentation_session = None

    @Slot()
    def _run_preview(self) -> None:
        if self._segmentation_session is None or self._thread is not None:
            return
        try:
            settings = self.current_settings()
            self._segmentation_session.set_segment_settings(settings)
        except Exception as error:
            self.status_label.setText(f"Invalid Cellpose settings: {error}")
            return
        request = PreviewRequest(
            frame_index=self.frame_slider.value(),
            channel=self.channel_combo.currentText(),
            z_index=self.z_slider.value(),
            user_settings=self.settings_panel.user_settings(),)
        self._active_request = request
        self._active_operation = "preview"
        self._thread = QThread(self)
        self._worker = PreviewWorker(self._segmentation_session, request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._preview_finished)
        self._worker.failed.connect(self._preview_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._set_running(True)
        self.status_label.setText(
            f"Running Cellpose on frame {request.frame_index + 1}, {request.channel}…")
        self._thread.start()

    @Slot()
    def _initialize_selected_model(self) -> None:
        if self._segmentation_session is None:
            return
        try:
            settings = self.current_settings()
        except Exception as error:
            self.status_label.setText(f"Invalid Cellpose settings: {error}")
            return
        if self._thread is not None:
            self._pending_model_settings = settings
            self.status_label.setText(
                "Model selection changed; the latest model will initialize next.")
            return
        self._start_model_initialization(settings)

    def _start_model_initialization(self, settings: SegmentSettings) -> None:
        request = ModelInitializationRequest(settings)
        self._pending_model_settings = None
        self._active_operation = "initialization"
        self._thread = QThread(self)
        self._worker = ModelInitializationWorker(request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._model_initialized)
        self._worker.failed.connect(self._model_initialization_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._set_running(True, initialization=True)
        self.status_label.setText("Initializing Cellpose model…")
        self._thread.start()

    @Slot(object)
    def _model_initialized(self, request: ModelInitializationRequest) -> None:
        del request
        self.status_label.setText("Cellpose model ready. Adjust settings or run a preview.")

    @Slot(object, str)
    def _model_initialization_failed(
        self, request: ModelInitializationRequest, message: str,
    ) -> None:
        del request
        self.status_label.setText(f"Cellpose model initialization failed: {message}")

    @Slot(object)
    def _preview_finished(self, outcome: PreviewOutcome) -> None:
        if outcome.request != self._active_request:
            return
        try:
            self._display_preview_mask(outcome.preview, outcome.request.z_index)
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        cache_note = "loaded from preview cache" if outcome.preview.from_cache else "segmented"
        self.status_label.setText(
            f"Frame {outcome.request.frame_index + 1}, {outcome.request.channel}: {cache_note}.")

    def _display_preview_mask(self,
                              preview: SegmentationPreview,
                              z_index: int,
                              ) -> None:
        mask = np.asarray(preview.mask)
        axes = preview.mask_axes
        if "Z" in axes:
            z_axis = axes.index("Z")
            mask = np.take(mask, z_index, axis=z_axis)
            axes = axes.replace("Z", "", 1)
        if axes != "YX":
            raise ValueError(f"Cannot display preview axes {preview.mask_axes!r}.")
        self.image_viewer.set_mask(mask)

    @Slot(str)
    def _preview_failed(self, message: str) -> None:
        self.status_label.setText(f"Cellpose preview failed: {message}")

    @Slot()
    def _thread_finished(self) -> None:
        thread = self._thread
        operation = self._active_operation
        self._thread = None
        self._worker = None
        self._active_request = None
        self._active_operation = None
        self._set_running(False, initialization=operation == "initialization")
        if thread is not None:
            thread.deleteLater()
        pending = self._pending_model_settings
        if pending is not None:
            self._start_model_initialization(pending)

    @Slot()
    def _apply_settings(self) -> None:
        if self._thread is not None:
            activity = ("model initialization"
                        if self._active_operation == "initialization"
                        else "preview")
            self.status_label.setText(
                f"Wait for the current Cellpose {activity} before applying settings.")
            return
        try:
            settings = self.current_settings()
        except Exception as error:
            self.status_label.setText(f"Invalid Cellpose settings: {error}")
            return
        self._provided_settings = settings
        if self._segmentation_session is not None:
            self._segmentation_session.set_segment_settings(settings)
        self.settings_applied.emit(settings)
        self.status_label.setText("Current Cellpose settings applied.")
        if self._close_on_apply:
            self.close()

    def current_settings(self) -> SegmentSettings:
        """
        Return the complete validated settings represented by the viewer.
        """
        if self._segmentation_session is None:
            raise RuntimeError("Load an experiment before applying settings.")
        payload: dict[str, Any] = self._segmentation_session.segment_settings.model_dump()
        payload["channel_to_segment"] = [self.channel_combo.currentText()]
        payload["nuclear_channel"] = self.settings_panel.selected_nuclear_channel
        payload["do_denoise"] = self.settings_panel.denoise.isChecked()
        payload["user_settings"] = {
            **self._segmentation_session.segment_settings.user_settings,
            **self.settings_panel.user_settings(),}
        return SegmentSettings.model_validate(payload)

    def _set_running(self, running: bool, *, initialization: bool = False) -> None:
        self.progress.setVisible(running)
        if initialization:
            self.settings_panel.run_button.setEnabled(not running)
            return
        self.settings_panel.set_running(running)
        self.directory_edit.setEnabled(not running)
        self.browse_button.setEnabled(not running)
        self.directory_browser.setEnabled(not running)
        self.frame_slider.setEnabled(not running)
        self.channel_combo.setEnabled(not running)
        self.z_slider.setEnabled(not running)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            activity = ("model initialization"
                        if self._active_operation == "initialization"
                        else "preview")
            self.status_label.setText(
                f"Wait for the current Cellpose {activity} before closing.")
            event.ignore()
            return
        super().closeEvent(event)
