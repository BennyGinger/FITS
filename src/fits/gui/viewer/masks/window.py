from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QEventLoop, QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import QApplication, QColorDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTabWidget, QWidget

from fits.environment.constant import FITS_ARRAY_NAME, FITS_REFERENCE_TEMPLATE, FITS_ROI_TEMPLATE
from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.common.information_dialog import MASK_HELP
from fits.gui.viewer.masks.reference_panel import ReferenceMaskPanel
from fits.gui.viewer.masks.roi_panel import RoiMaskPanel
from fits.gui.viewer.masks.preview import MaskPreviewWorker
from fits.tasks.reference_mask import ReferenceMaskSession
from fits.tasks.roi_mask import RoiSession


class _PlaneCoordinates(TypedDict):
    frame_index: int
    channel: str
    z_index: int


class _InterpolationOptions(TypedDict):
    frame_index: int
    channel: str
    z_index: int
    extrapolate_start: bool
    extrapolate_end: bool


class MaskDrawingWindow(ImageToolWindow):
    """Create and edit reference and ROI masks in a shared image context."""

    mask_saved = Signal(str, object)

    file_filters = (FITS_ARRAY_NAME, FITS_REFERENCE_TEMPLATE.format(label="*"),
                    FITS_ROI_TEMPLATE.format(label="*"))
    help_gui = "REF / ROI"
    tool_help = MASK_HELP

    def __init__(self, experiments_dir: str | Path | None = None,
                 parent: QWidget | None = None) -> None:
        self._reference_session: ReferenceMaskSession | None = None
        self._roi_session: RoiSession | None = None
        self._reference_path: Path | None = None
        self._roi_path: Path | None = None
        self._preview_thread: QThread | None = None
        self._preview_worker: MaskPreviewWorker | None = None
        self._preview_failed_key: tuple | None = None
        self._threshold_image_key: tuple | None = None
        super().__init__(experiments_dir, parent)
        self.setWindowTitle("FITS Mask Drawing")
        self._refresh_mask_colour_controls()

    def _build_tools(self) -> QWidget:
        self.reference_panel = ReferenceMaskPanel()
        self.roi_panel = RoiMaskPanel()
        self.reference_panel.overlay_widget.hide()
        self.roi_panel.overlay_widget.hide()
        self.tool_tabs = QTabWidget()
        self.tool_tabs.addTab(self.reference_panel, "Reference")
        self.tool_tabs.addTab(self.roi_panel, "ROI")
        self.tool_panel = self.tool_tabs
        return self.tool_panel

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        self.reference_mask_colour = QColor(255, 215, 0)
        self.reference_mask_colour_button = QPushButton("Mask colour")
        self.reference_mask_colour_button.setToolTip("Change the colour of the displayed binary mask.")
        self._set_reference_mask_colour_button()
        layout.addWidget(self.reference_mask_colour_button)

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key.Key_D:
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self._clear_reference_drawing()
                return True
            if event.modifiers() == (Qt.KeyboardModifier.ControlModifier
                                     | Qt.KeyboardModifier.ShiftModifier):
                self._clear_all_drawing()
                return True
        if (event.modifiers() in (Qt.KeyboardModifier.NoModifier,
                                  Qt.KeyboardModifier.ShiftModifier)
                and event.key() == Qt.Key.Key_S):
            if self._reference_tool_active():
                self._save_reference_mask()
            else:
                self._save_roi_mask()
            return True
        return False

    def _undo(self) -> None:
        self._undo_reference_drawing()

    def _connect_tools(self) -> None:
        self.preview_status = QLabel()
        self.preview_status.hide()
        cast(QHBoxLayout, self.status_bar.layout()).insertWidget(1, self.preview_status)
        self.reference_panel.drawing_options_changed.connect(
            self._update_drawing_options)
        self.reference_panel.undo_requested.connect(
            self._undo_reference_drawing)
        self.reference_panel.clear_requested.connect(
            self._clear_reference_drawing)
        self.reference_panel.clear_all_requested.connect(self._clear_all_drawing)
        self.reference_panel.save_requested.connect(
            self._save_reference_mask)
        self.reference_panel.mask_visibility_changed.connect(
            self.image_viewer.set_mask_visible)
        self.reference_panel.mask_opacity_changed.connect(
            self.image_viewer.set_mask_opacity)
        self.roi_panel.drawing_options_changed.connect(self._update_drawing_options)
        self.roi_panel.undo_requested.connect(self._undo_reference_drawing)
        self.roi_panel.clear_requested.connect(self._clear_reference_drawing)
        self.roi_panel.clear_all_requested.connect(self._clear_all_drawing)
        self.roi_panel.save_requested.connect(self._save_roi_mask)
        self.roi_panel.automatic_current_requested.connect(self._apply_otsu_threshold)
        self.roi_panel.automatic_stack_requested.connect(self._apply_otsu_stack)
        self.roi_panel.threshold_changed.connect(self._apply_roi_threshold)
        self.roi_panel.manual_stack_requested.connect(self._apply_manual_roi_stack)
        self.roi_panel.fill_holes_requested.connect(self._fill_roi_holes)
        self.roi_panel.remove_small_objects_requested.connect(
            self._remove_small_roi_objects)
        self.roi_panel.mask_visibility_changed.connect(self.image_viewer.set_mask_visible)
        self.roi_panel.mask_opacity_changed.connect(self.image_viewer.set_mask_opacity)
        self.reference_panel.interpolation_preview_changed.connect(
            self._display_selection)
        self.roi_panel.interpolation_preview_changed.connect(
            self._display_selection)
        self.image_viewer.drawing_changed.connect(
            self._reference_drawing_changed)
        self.image_viewer.drawing_started.connect(
            self._disable_active_interpolation_preview)
        self.image_viewer.enable_mask_movement()
        self.image_viewer.mask_moved.connect(self._move_binary_mask)
        self.image_viewer.drawing_finished.connect(
            self._replace_reference_drawing)
        self.tool_tabs.currentChanged.connect(self._tool_changed)
        self.reference_mask_colour_button.clicked.connect(self._choose_reference_mask_colour)

    @Slot(object)
    def _path_selected(self, selected: object) -> None:
        if not isinstance(selected, (str, Path)):
            return
        path = Path(selected)
        if path.is_dir():
            source = path / FITS_ARRAY_NAME
            if source.is_file() and self.directory_browser.select_path(source):
                return
        else:
            reference_pattern = FITS_REFERENCE_TEMPLATE.format(label="*")
            if path.match(reference_pattern):
                source = path.with_name(FITS_ARRAY_NAME)
                if not source.is_file():
                    self.status_label.setText(
                        f"Reference mask has no sibling {FITS_ARRAY_NAME}.")
                    return
                reference_index = self.tool_tabs.indexOf(self.reference_panel)
                if reference_index >= 0:
                    self.tool_tabs.setCurrentIndex(reference_index)
                self._open_source(source, reference_path=path)
                return
            roi_pattern = FITS_ROI_TEMPLATE.format(label="*")
            if path.match(roi_pattern):
                source = path.with_name(FITS_ARRAY_NAME)
                if not source.is_file():
                    self.status_label.setText(f"ROI mask has no sibling {FITS_ARRAY_NAME}.")
                    return
                roi_index = self.tool_tabs.indexOf(self.roi_panel)
                if roi_index >= 0:
                    self.tool_tabs.setCurrentIndex(roi_index)
                self._open_source(source, roi_path=path)
                return
            source = path
        if source.name != FITS_ARRAY_NAME or not source.is_file():
            self.status_label.setText(f"Select an experiment containing {FITS_ARRAY_NAME}.")
            return
        self._open_source(source)

    def _open_source(self,
                     source: Path,
                     *,
                     reference_path: Path | None = None,
                     roi_path: Path | None = None,
                     ) -> None:
        if reference_path is None:
            reference_path = next((path for path in sorted(source.parent.glob(
                FITS_REFERENCE_TEMPLATE.format(label="*"))) if path.is_file()), None)
        if roi_path is None:
            roi_path = next((path for path in sorted(source.parent.glob(
                FITS_ROI_TEMPLATE.format(label="*"))) if path.is_file()), None)
        if (source == self._source_path and reference_path == self._reference_path
                and roi_path == self._roi_path):
            return
        self._close_session()
        try:
            self._reference_session = ReferenceMaskSession(
                source, reference_path=reference_path)
            self._roi_session = RoiSession(source, roi_path=roi_path)
        except Exception as error:
            self._reference_session = None
            self._roi_session = None
            self.status_label.setText(str(error))
            return
        self._source_path = source
        self._reference_path = reference_path
        self._roi_path = roi_path
        self._image_session = self._reference_session
        self.reference_panel.set_available_axes(
            self._reference_session.axes, self._reference_session.shape)
        self.roi_panel.set_available_axes(
            self._roi_session.axes, self._roi_session.shape)
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        self.channel_combo.addItems(self._image_session.channel_labels)
        active_session = self._active_binary_session()
        if active_session is not None and not active_session.loaded_channels:
            if self._reference_session.loaded_channels:
                active_session = self._reference_session
            elif self._roi_session.loaded_channels:
                active_session = self._roi_session
        selected_channel = (active_session.loaded_channels[0]
                            if active_session is not None and active_session.loaded_channels
                            else None)
        channel_index = self.channel_combo.findText(str(selected_channel))
        self.channel_combo.setCurrentIndex(max(channel_index, 0))
        self.channel_combo.blockSignals(False)
        self.frame_slider.setRange(0, self._image_session.frame_count - 1)
        self.z_slider.setRange(0, self._image_session.plane_count - 1)
        self.frame_slider.setValue(0)
        self.z_slider.setValue(0)
        self._set_source_controls_enabled(True)
        self.reference_panel.label_edit.setText(
            self._reference_session.reference_label or "")
        self.roi_panel.label_edit.setText(self._roi_session.roi_label or "")
        self.roi_panel.reset_for_source()
        self._update_drawing_options()
        self._display_selection()
        self.status_label.setText(
            f"Loaded {source.parent.name} — axes "
            f"{self._image_session.axes}, shape {self._image_session.shape}.")

    def _display_overlay(self, image, frame, channel, z_index) -> None:
        session = self._active_binary_session()
        panel = self._active_binary_panel()
        if session is None or panel is None:
            return
        display_mask = self._binary_display_mask(
            session, panel, frame, channel, z_index)
        self.image_viewer.set_drawing_mask(display_mask)
        panel.set_undo_available(False)
        self.image_viewer.set_drawing_enabled(True)
        self.image_viewer.set_mask_visible(self.show_mask.isChecked())
        self.image_viewer.set_mask_opacity(self.mask_opacity.value() / 100.0)
        if self._roi_tool_active() and isinstance(session, RoiSession):
            image_key = id(self._image_session), frame, channel, z_index
            if image_key != self._threshold_image_key:
                self.roi_panel.set_threshold_image(image)
                self._threshold_image_key = image_key
            threshold_range = session.threshold_range(
                frame_index=frame, channel=channel, z_index=z_index)
            if threshold_range is not None:
                self.roi_panel.set_threshold_range(*threshold_range)

    def _clear_tools(self) -> None:
        if self._preview_thread is not None:
            self._preview_thread.requestInterruption()
            self._preview_thread.quit()
            self._preview_thread.wait()
            self._preview_thread.deleteLater()
            self._preview_thread = None
            self._preview_worker = None
        self.image_viewer.set_preview_loading(False)
        self.preview_status.hide()
        self.progress.hide()
        self._preview_failed_key = None
        self._threshold_image_key = None
        if self._reference_session is not None:
            self._reference_session.close()
        if self._roi_session is not None:
            self._roi_session.close()
        self._reference_session = None
        self._roi_session = None
        self._reference_path = None
        self._roi_path = None
        self.reference_panel.set_undo_available(False)
        self.roi_panel.set_undo_available(False)
        self.reference_panel.label_edit.clear()
        self.roi_panel.label_edit.clear()

    def _refresh_mask_colour_controls(self) -> None:
        self.image_viewer.set_mask_color(self.reference_mask_colour)
        self.image_viewer.set_drawing_style(self.reference_mask_colour)

    def _reference_tool_active(self) -> bool:
        return self.tool_tabs.currentWidget() is self.reference_panel

    def _roi_tool_active(self) -> bool:
        return self.tool_tabs.currentWidget() is self.roi_panel

    def _binary_tool_active(self) -> bool:
        return self._reference_tool_active() or self._roi_tool_active()

    def _active_binary_panel(self) -> ReferenceMaskPanel | RoiMaskPanel | None:
        if self._reference_tool_active():
            return self.reference_panel
        if self._roi_tool_active():
            return self.roi_panel
        return None

    def _active_binary_session(self) -> ReferenceMaskSession | RoiSession | None:
        return self._reference_session if self._reference_tool_active() else (
            self._roi_session if self._roi_tool_active() else None)

    @Slot()
    def _disable_active_interpolation_preview(self) -> None:
        panel = self._active_binary_panel()
        if panel is not None and panel.live_preview.isChecked():
            panel.live_preview.setChecked(False)

    def _binary_display_mask(
            self,
            session: ReferenceMaskSession | RoiSession,
            panel: ReferenceMaskPanel | RoiMaskPanel,
            frame_index: int, channel: str, z_index: int) -> NDArray[np.uint8]:
        axis = panel.preview_interpolation_axis
        if panel.interpolation_preview_enabled and axis is not None:
            options: _InterpolationOptions = {
                "frame_index": frame_index, "channel": channel, "z_index": z_index,
                "extrapolate_start": panel.extrapolate_start.isChecked(),
                "extrapolate_end": panel.extrapolate_end.isChecked()}
            key = session.preview_key(axis, **options)
            cached = session.preview_cache.cached_plane(
                key, frame_index if axis == "T" else z_index)
            if cached is not None:
                if isinstance(session, RoiSession):
                    cached = session._included(cached)
                if self._preview_thread is not None and self._preview_worker is not None:
                    if self._preview_worker.key != key:
                        self._preview_thread.requestInterruption()
                    else:
                        self._preview_worker.position = frame_index if axis == "T" else z_index
                self.image_viewer.set_preview_loading(False)
                if self._preview_thread is None:
                    self.preview_status.hide()
                    self.progress.hide()
                return cached
            self.image_viewer.set_preview_loading(key != self._preview_failed_key)
            if self._preview_thread is not None:
                if self._preview_worker is not None:
                    if self._preview_worker.key != key:
                        self._preview_thread.requestInterruption()
                    else:
                        self._preview_worker.position = frame_index if axis == "T" else z_index
            elif key != self._preview_failed_key:
                worker = MaskPreviewWorker(session, key, axis, options)
                thread = QThread(self)
                worker.moveToThread(thread)
                thread.started.connect(worker.run)
                worker.progress.connect(self._preview_progress)
                worker.ready.connect(self._preview_ready)
                worker.plane_ready.connect(self._preview_plane_ready)
                worker.failed.connect(self._preview_failed)
                worker.done.connect(thread.quit)
                worker.done.connect(worker.deleteLater)
                thread.finished.connect(self._preview_finished)
                self._preview_thread, self._preview_worker = thread, worker
                self.preview_status.setText("Preparing propagation preview…")
                self.preview_status.show()
                self.progress.setRange(0, 0)
                self.progress.show()
                thread.start()
        else:
            self.image_viewer.set_preview_loading(False)
            if self._preview_thread is not None:
                self._preview_thread.requestInterruption()
            self.preview_status.hide()
            self.progress.hide()
        if isinstance(session, RoiSession):
            return session.display_mask_plane(frame_index, channel, z_index)
        return session.mask_plane(frame_index, channel, z_index)

    @Slot(object, int)
    def _preview_plane_ready(self, key: tuple, index: int) -> None:
        worker = self._preview_worker
        if worker is None or self.sender() is not worker:
            return
        panel = self._active_binary_panel()
        session = self._active_binary_session()
        if (session is None or session is not worker.session or panel is None
                or not panel.interpolation_preview_enabled or self.image_viewer._drawing_active):
            return
        current = self.frame_slider.value() if worker.axis == "T" else self.z_slider.value()
        if current != index or session.preview_key(worker.axis, **worker.options) != key:
            return
        self._display_selection()

    @Slot(str)
    def _preview_progress(self, stage: str) -> None:
        if self.sender() is self._preview_worker:
            self.preview_status.setText(stage + "…")

    @Slot(object)
    def _preview_ready(self, _key: tuple) -> None:
        if (self.sender() is self._preview_worker and self.image_viewer._loading_visible
                and not self.image_viewer._drawing_active):
            self._display_selection()

    @Slot(str)
    def _preview_failed(self, message: str) -> None:
        if self._preview_worker is not None and self.sender() is self._preview_worker:
            self._preview_failed_key = self._preview_worker.key
            self.status_label.setText(f"Propagation preview failed: {message}")

    @Slot()
    def _preview_finished(self) -> None:
        thread = self.sender()
        if thread is not self._preview_thread:
            return
        self._preview_thread = None
        self._preview_worker = None
        self.preview_status.hide()
        self.progress.hide()
        if isinstance(thread, QThread):
            thread.deleteLater()
        panel = self._active_binary_panel()
        if (self._active_binary_session() is not None and panel is not None
                and panel.interpolation_preview_enabled and self.image_viewer._loading_visible
                and not self.image_viewer._drawing_active):
            self._display_selection()

    @Slot(int)
    def _tool_changed(self, _: int) -> None:
        session = self._active_binary_session()
        if (session is not None and session.loaded_channels
                and self.channel_combo.currentText() not in session.loaded_channels):
            self.channel_combo.setCurrentText(session.loaded_channels[0])
        self._refresh_mask_colour_controls()
        self._update_drawing_options()
        self._display_selection()

    def _set_reference_mask_colour_button(self) -> None:
        color = self.reference_mask_colour.name()
        self.reference_mask_colour_button.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: black; }}")

    @Slot()
    def _choose_reference_mask_colour(self) -> None:
        selected = QColorDialog.getColor(
            self.reference_mask_colour, self, "Mask colour")
        if not selected.isValid():
            return
        self.reference_mask_colour = selected
        self._set_reference_mask_colour_button()
        if self._binary_tool_active():
            self._refresh_mask_colour_controls()

    @Slot()
    def _update_drawing_options(self) -> None:
        panel = self._active_binary_panel()
        if panel is not None:
            self.image_viewer.set_drawing_options(
                panel.drawing_mode, panel.drawing_tool,
                panel.drawing_operation, panel.brush_size.value())
        self.image_viewer.set_drawing_enabled(
            self._binary_tool_active() and self._active_binary_session() is not None)

    @Slot()
    def _reference_drawing_changed(self) -> None:
        panel = self._active_binary_panel()
        if panel is None:
            return
        panel.set_undo_available(self.image_viewer.can_undo_drawing)

    @Slot(object)
    def _replace_reference_drawing(self, mask: object) -> None:
        session = self._active_binary_session()
        if session is None or not self._binary_tool_active():
            return
        try:
            coordinates: _PlaneCoordinates = {
                "frame_index": self.frame_slider.value(),
                "channel": self.channel_combo.currentText(),
                "z_index": self.z_slider.value()}
            if isinstance(session, RoiSession):
                comparison = self._binary_display_mask(
                    session, self.roi_panel, coordinates["frame_index"],
                    coordinates["channel"], coordinates["z_index"])
                session.apply_display_edit(
                    np.asarray(mask), comparison_mask=comparison,
                    edited_pixels=self.image_viewer.last_drawing_selection,
                    operation=self.image_viewer.last_drawing_operation,
                    **coordinates)
            elif self.reference_panel.drawing_mode == "replace":
                session.replace_display_mask(np.asarray(mask), **coordinates)
            else:
                comparison = self._binary_display_mask(
                    session, self.reference_panel, coordinates["frame_index"],
                    coordinates["channel"], coordinates["z_index"])
                session.apply_display_edit(
                    np.asarray(mask), comparison_mask=comparison, **coordinates)
        except Exception as error:
            self.status_label.setText(f"Could not store binary-mask drawing: {error}")
            return
        self.status_label.setText("Binary-mask drawing updated in the current session.")

    @Slot(object, object)
    def _move_binary_mask(self, moved: object, previous: object) -> None:
        session = self._active_binary_session()
        if session is None:
            return
        session.apply_display_edit(
            np.asarray(moved), comparison_mask=np.asarray(previous),
            frame_index=self.frame_slider.value(), channel=self.channel_combo.currentText(),
            z_index=self.z_slider.value())
        panel = self._active_binary_panel()
        if panel is not None:
            panel.set_undo_available(True)
        self.status_label.setText("Moved the selected mask region. Ctrl+Z to undo.")

    @Slot()
    def _undo_reference_drawing(self) -> None:
        session = self._active_binary_session()
        panel = self._active_binary_panel()
        if session is None or panel is None:
            return
        coordinates: _PlaneCoordinates = {
            "frame_index": self.frame_slider.value(),
            "channel": self.channel_combo.currentText(),
            "z_index": self.z_slider.value()}
        restored = session.undo_display_edit(**coordinates)
        if restored is None:
            return
        self.image_viewer.undo_drawing()
        self.image_viewer.set_drawing_mask(self._binary_display_mask(
            session, panel, coordinates["frame_index"],
            coordinates["channel"], coordinates["z_index"]))
        panel.set_undo_available(self.image_viewer.can_undo_drawing)
        self.status_label.setText("Restored the previous binary-mask drawing.")

    @Slot()
    def _clear_reference_drawing(self) -> None:
        session = self._active_binary_session()
        panel = self._active_binary_panel()
        if session is None or panel is None:
            return
        self._disable_active_interpolation_preview()
        self.image_viewer.clear_drawing_mask()
        session.clear_mask_plane(
            frame_index=self.frame_slider.value(),
            channel=self.channel_combo.currentText(),
            z_index=self.z_slider.value(),)
        panel.set_undo_available(
            self.image_viewer.can_undo_drawing
            if not isinstance(session, RoiSession) else False)
        self.status_label.setText("Binary mask cleared from the current plane.")

    @Slot()
    def _clear_all_drawing(self) -> None:
        session = self._active_binary_session()
        if session is None:
            return
        self._disable_active_interpolation_preview()
        channel = self.channel_combo.currentText()
        session.clear_stack(channel=channel)
        self._display_selection()
        self.status_label.setText(
            f"Cleared all frames and Z planes of {channel} in this session. "
            "The saved mask is unchanged until you save.")

    @contextmanager
    def _saving_overlay(self) -> Iterator[None]:
        viewer = self.image_viewer
        viewer.set_preview_loading(True, "Preparation of saving…", animate=False)
        # Paint before entering the synchronous save. Ignore user input while
        # queued preview completion and paint events are drained.
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        viewer.set_preview_loading(True, "Preparation of saving…", animate=False)
        viewer.loading_overlay.repaint()
        try:
            yield
        finally:
            viewer.set_preview_loading(False, animate=False)

    @Slot()
    def _save_reference_mask(self) -> None:
        if self._reference_session is None:
            return
        label = self.reference_panel.reference_label
        channel = self.channel_combo.currentText()
        try:
            saved_channels = self._reference_session.saved_channels(label)
            if saved_channels and channel not in saved_channels:
                QMessageBox.information(
                    self,
                    "Add reference channel",
                    f"{FITS_REFERENCE_TEMPLATE.format(label=label)} already "
                    f"contains {', '.join(saved_channels)}. The {channel} "
                    "reference channel will be added to the same file.")
            with self._saving_overlay():
                path = self._reference_session.save(
                    label,
                    channel=channel,
                    interpolation_axis=self.reference_panel.selected_interpolation_axis,
                    extrapolate_start=self.reference_panel.extrapolate_start.isChecked(),
                    extrapolate_end=self.reference_panel.extrapolate_end.isChecked(),)
        except FileExistsError as error:
            answer = QMessageBox.question(
                self,
                "Replace reference mask?",
                f"{error}\n\nReplace the existing file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,)
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                with self._saving_overlay():
                    path = self._reference_session.save(
                        label,
                        channel=channel,
                        interpolation_axis=self.reference_panel.selected_interpolation_axis,
                        extrapolate_start=self.reference_panel.extrapolate_start.isChecked(),
                        extrapolate_end=self.reference_panel.extrapolate_end.isChecked(),
                        overwrite=True,)
            except Exception as overwrite_error:
                self.status_label.setText(
                    f"Could not save reference mask: {overwrite_error}")
                return
        except Exception as error:
            self.status_label.setText(f"Could not save reference mask: {error}")
            return
        self.status_label.setText(
            f"Saved reference mask to {path.name}. Current channel: "
            f"{self.channel_combo.currentText()}.")
        self.mask_saved.emit("reference", path)

    @Slot()
    def _apply_otsu_threshold(self) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        try:
            image = self._image_session.display_frame(
                self.frame_slider.value(), self.channel_combo.currentText(),
                self.z_slider.value()) if self._image_session is not None else None
            if image is None:
                return
            threshold = self._roi_session.apply_otsu(
                frame_index=self.frame_slider.value(),
                channel=self.channel_combo.currentText(),
                z_index=self.z_slider.value())
            if threshold is None:
                self.image_viewer.set_drawing_mask(
                    self._roi_session.display_mask_plane(
                        self.frame_slider.value(), self.channel_combo.currentText(),
                        self.z_slider.value()))
                self.status_label.setText(
                    "Current plane has no intensity contrast; its ROI mask was cleared.")
                return
            maximum = float(np.nanmax(image))
            self.roi_panel.set_threshold_range(threshold, maximum)
            self.image_viewer.set_drawing_mask(
                self._roi_session.display_mask_plane(
                    self.frame_slider.value(), self.channel_combo.currentText(),
                    self.z_slider.value()))
            self.status_label.setText(f"Applied Otsu threshold {threshold:g}.")
        except Exception as error:
            self.status_label.setText(f"Could not create automatic ROI: {error}")

    @Slot()
    def _apply_otsu_stack(self) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        try:
            empty_planes = self._roi_session.threshold_stack(
                channel=self.channel_combo.currentText())
            self._display_selection()
            message = (f"Created independent automatic ROI masks for the complete "
                       f"{self.channel_combo.currentText()} stack.")
            if empty_planes:
                message += f" Cleared {empty_planes} plane(s) without intensity contrast."
            self.status_label.setText(message)
        except Exception as error:
            self.status_label.setText(f"Could not threshold ROI stack: {error}")

    @Slot(float, float)
    def _apply_manual_roi_stack(self, minimum: float, maximum: float) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        try:
            self._roi_session.threshold_stack_range(
                minimum, maximum, channel=self.channel_combo.currentText())
            self._display_selection()
            self.roi_panel.set_threshold_range(minimum, maximum)
            self.status_label.setText(
                f"Applied ROI intensity range {minimum:g} to {maximum:g} "
                f"to the complete {self.channel_combo.currentText()} stack.")
        except Exception as error:
            self.status_label.setText(f"Could not apply ROI range to stack: {error}")

    @Slot()
    def _fill_roi_holes(self) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        coordinates: _PlaneCoordinates = {
            "frame_index": self.frame_slider.value(),
            "channel": self.channel_combo.currentText(),
            "z_index": self.z_slider.value()}
        try:
            changed = self._roi_session.fill_holes_stack(channel=coordinates["channel"])
            self.image_viewer.set_drawing_mask(
                self._roi_session.display_mask_plane(**coordinates))
            self.roi_panel.set_undo_available(bool(changed))
            self.status_label.setText(
                f"Filled holes on {changed} plane(s) in the complete "
                f"{coordinates['channel']} ROI stack; manual exclusions preserved.")
        except Exception as error:
            self.status_label.setText(f"Could not fill ROI holes: {error}")

    @Slot(int)
    def _remove_small_roi_objects(self, minimum_size: int) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        coordinates: _PlaneCoordinates = {
            "frame_index": self.frame_slider.value(),
            "channel": self.channel_combo.currentText(),
            "z_index": self.z_slider.value()}
        try:
            changed = self._roi_session.remove_small_objects_stack(
                minimum_size, channel=coordinates["channel"])
            self.image_viewer.set_drawing_mask(
                self._roi_session.display_mask_plane(**coordinates))
            self.roi_panel.set_undo_available(bool(changed))
            self.status_label.setText(
                f"Removed ROI objects smaller than {minimum_size} px² "
                f"on {changed} plane(s) in the complete {coordinates['channel']} stack.")
        except Exception as error:
            self.status_label.setText(
                f"Could not remove small ROI objects: {error}")

    @Slot(float, float)
    def _apply_roi_threshold(self, minimum: float, maximum: float) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        try:
            self._roi_session.threshold_plane(
                minimum, maximum, frame_index=self.frame_slider.value(),
                channel=self.channel_combo.currentText(),
                z_index=self.z_slider.value())
            self.image_viewer.set_drawing_mask(
                self._roi_session.display_mask_plane(
                    self.frame_slider.value(), self.channel_combo.currentText(),
                    self.z_slider.value()))
            self.roi_panel.set_undo_available(False)
            self.status_label.setText(
                f"ROI includes intensities from {minimum:g} to {maximum:g}.")
        except Exception as error:
            self.status_label.setText(f"Could not apply ROI threshold: {error}")

    @Slot()
    def _save_roi_mask(self) -> None:
        if self._roi_session is None:
            return
        label = self.roi_panel.roi_label
        channel = self.channel_combo.currentText()
        try:
            saved_channels = self._roi_session.saved_channels(label)
            if saved_channels and channel not in saved_channels:
                QMessageBox.information(
                    self, "Add ROI channel",
                    f"{FITS_ROI_TEMPLATE.format(label=label)} already contains "
                    f"{', '.join(saved_channels)}. The {channel} ROI channel "
                    "will be added to the same file.")
            with self._saving_overlay():
                path = self._roi_session.save(
                    label, channel=channel,
                    interpolation_axis=self.roi_panel.selected_interpolation_axis,
                    extrapolate_start=self.roi_panel.extrapolate_start.isChecked(),
                    extrapolate_end=self.roi_panel.extrapolate_end.isChecked())
        except FileExistsError as error:
            answer = QMessageBox.question(
                self, "Replace ROI mask?", f"{error}\n\nReplace the existing file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                with self._saving_overlay():
                    path = self._roi_session.save(
                        label, channel=channel,
                        interpolation_axis=self.roi_panel.selected_interpolation_axis,
                        extrapolate_start=self.roi_panel.extrapolate_start.isChecked(),
                        extrapolate_end=self.roi_panel.extrapolate_end.isChecked(),
                        overwrite=True)
            except Exception as overwrite_error:
                self.status_label.setText(f"Could not save ROI mask: {overwrite_error}")
                return
        except Exception as error:
            self.status_label.setText(f"Could not save ROI mask: {error}")
            return
        self.status_label.setText(
            f"Saved ROI mask to {path.name}. Current channel: {channel}.")
        self.mask_saved.emit("roi", path)
