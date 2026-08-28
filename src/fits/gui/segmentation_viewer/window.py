from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QEvent, QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFileDialog,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from fits.environment.constant import FITS_ARRAY_NAME
from fits.gui.run_browser import DirectoryBrowser
from fits.gui.segmentation_viewer.image_viewer import SegmentationImageViewer
from fits.gui.segmentation_viewer.settings_panel import CellposeSettingsPanel
from fits.gui.segmentation_viewer.worker import PreviewOutcome, PreviewRequest, PreviewWorker
from fits.gui.settings_adapter import SAVED_SETTINGS_NAME, SettingsAdapter
from fits.settings.models import SegmentSettings
from fits.tasks.segmentation.preview_cache import SegmentationPreview
from fits.tasks.segmentation.tuning import SegmentationTuningSession


class SegmentationViewerWindow(QMainWindow):
    """
    Browse FITS experiments and tune segmentation on selected stack planes.

    The window can run independently or be embedded in a FITS workflow. When
    Apply settings is clicked, ``settings_applied`` emits a complete validated
    ``SegmentSettings`` instance for the currently displayed channel.
    """

    settings_applied = Signal(object)

    def __init__(self,
                 experiments_dir: str | Path | None = None,
                 segment_settings: SegmentSettings | Mapping[str, Any] | None = None,
                 parent: QWidget | None = None,
                 ) -> None:
        super().__init__(parent)
        self.setWindowTitle("FITS Segmentation Viewer")
        self.resize(1700, 1150)

        self._provided_settings = (SegmentSettings.model_validate(segment_settings)
                                   if segment_settings is not None
                                   else None)
        self._session: SegmentationTuningSession | None = None
        self._source_path: Path | None = None
        self._thread: QThread | None = None
        self._worker: PreviewWorker | None = None
        self._active_request: PreviewRequest | None = None
        self._displayed_channel: str | None = None
        self._channel_levels: dict[str, tuple[float, float]] = {}

        self._build_ui()
        self._connect_signals()
        self._install_keyboard_shortcuts()
        self._set_source_controls_enabled(False)
        if experiments_dir is not None:
            self._set_experiments_directory(experiments_dir)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(8, 8, 8, 8)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        outer_layout.addWidget(main_splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        directory_row = QHBoxLayout()
        directory_row.addWidget(QLabel("Experiments directory"))
        self.directory_edit = QLineEdit()
        self.directory_edit.setPlaceholderText("Choose a directory containing experiments")
        directory_row.addWidget(self.directory_edit, 1)
        self.browse_button = QPushButton("Browse")
        directory_row.addWidget(self.browse_button)
        left_layout.addLayout(directory_row)

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.directory_browser = DirectoryBrowser(
            "Experiments directory contents",
            file_name_filters=(FITS_ARRAY_NAME,),)
        left_splitter.addWidget(self.directory_browser)

        lut_container = QWidget()
        lut_layout = QVBoxLayout(lut_container)
        lut_layout.setContentsMargins(0, 0, 0, 0)
        lut_title = QLabel("Image LUT")
        lut_title.setStyleSheet("font-weight: bold;")
        lut_layout.addWidget(lut_title)
        self.image_viewer = SegmentationImageViewer()
        channel_row = QHBoxLayout()
        channel_row.addWidget(QLabel("Channel"))
        self.channel_combo = QComboBox()
        channel_row.addWidget(self.channel_combo, 1)
        lut_layout.addLayout(channel_row)
        mode_row = QHBoxLayout()
        self.colour_lut_button = QPushButton("Colour")
        self.colour_lut_button.setCheckable(True)
        self.colour_lut_button.setChecked(True)
        mode_row.addWidget(self.colour_lut_button)
        self.grayscale_lut_button = QPushButton("Grayscale")
        self.grayscale_lut_button.setCheckable(True)
        mode_row.addWidget(self.grayscale_lut_button)
        self.lut_mode_group = QButtonGroup(self)
        self.lut_mode_group.setExclusive(True)
        self.lut_mode_group.addButton(self.colour_lut_button)
        self.lut_mode_group.addButton(self.grayscale_lut_button)
        lut_layout.addLayout(mode_row)
        lut_layout.addWidget(self.image_viewer.histogram)
        lut_actions = QHBoxLayout()
        self.auto_scale_button = QPushButton("Auto-scale")
        lut_actions.addWidget(self.auto_scale_button)
        self.full_range_button = QPushButton("Full range")
        lut_actions.addWidget(self.full_range_button)
        lut_layout.addLayout(lut_actions)
        left_splitter.addWidget(lut_container)

        self.settings_panel = CellposeSettingsPanel()
        left_splitter.addWidget(self.settings_panel)
        left_splitter.setStretchFactor(0, 2)
        left_splitter.setStretchFactor(1, 2)
        left_splitter.setStretchFactor(2, 6)
        left_splitter.setSizes([230, 180, 570])
        left_layout.addWidget(left_splitter)
        main_splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        info_row = QHBoxLayout()
        info_row.addStretch(1)
        self.info_button = QToolButton()
        self.info_button.setText("i")
        self.info_button.setToolTip("Viewer information and keyboard shortcuts")
        self.info_button.setFixedSize(26, 26)
        self.info_button.setStyleSheet(
            "QToolButton { border: 1px solid #888; border-radius: 13px; "
            "font-weight: bold; font-style: italic; }")
        info_row.addWidget(self.info_button)
        right_layout.addLayout(info_row)
        right_layout.addWidget(self.image_viewer, 1)
        navigation = QHBoxLayout()
        self.frame_slider, self.frame_value = self._navigation_control("Frame", navigation)
        self.z_slider, self.z_value = self._navigation_control("Z", navigation)
        right_layout.addLayout(navigation)
        main_splitter.addWidget(right)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes([500, 1050])

        self.status_bar = QWidget()
        self.status_bar.setFixedHeight(28)
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("Choose an experiments directory, then select a FITS experiment.")
        status_layout.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.hide()
        status_layout.addWidget(self.progress)
        outer_layout.addWidget(self.status_bar)

    def _connect_signals(self) -> None:
        self.browse_button.clicked.connect(self._browse)
        self.directory_edit.returnPressed.connect(
            lambda: self._set_experiments_directory(self.directory_edit.text()))
        self.directory_browser.path_selected.connect(self._path_selected)
        self.frame_slider.valueChanged.connect(self._display_selection)
        self.channel_combo.currentIndexChanged.connect(self._display_selection)
        self.z_slider.valueChanged.connect(self._display_selection)
        self.settings_panel.run_requested.connect(self._run_preview)
        self.settings_panel.apply_requested.connect(self._apply_settings)
        self.settings_panel.mask_visibility_changed.connect(
            self.image_viewer.set_mask_visible)
        self.settings_panel.mask_opacity_changed.connect(
            self.image_viewer.set_mask_opacity)
        self.colour_lut_button.toggled.connect(self.image_viewer.set_coloured_lut)
        self.auto_scale_button.clicked.connect(self.image_viewer.auto_scale)
        self.full_range_button.clicked.connect(self.image_viewer.full_range)
        self.info_button.clicked.connect(self._show_information)

    @Slot()
    def _show_information(self) -> None:
        fits_version = self._package_version("fits")
        kit_version = self._package_version("cellpose-kit")
        text = (
            "Preview Cellpose segmentation on individual frames or Z volumes "
            "before applying the selected settings to a FITS pipeline. Browse "
            "experiments, adjust image contrast, compare channels and restore "
            "cached preview masks without modifying pipeline artifacts.\n\n"
            "Keyboard shortcuts\n"
            "X    Toggle mask overlay\n"
            "R    Run preview\n"
            "← / →    Previous / next frame\n"
            "↑ / ↓    Previous / next Z plane\n"
            "C    Next channel\n"
            "S    Apply settings\n\n"
            f"FITS {fits_version}\n"
            f"cellpose-kit {kit_version}\n"
            f"{self.settings_panel.version_label.text()}")
        QMessageBox.information(self, "About FITS Segmentation Viewer", text)

    @staticmethod
    def _package_version(distribution: str) -> str:
        try:
            return version(distribution)
        except PackageNotFoundError:
            return "development version"

    def _install_keyboard_shortcuts(self) -> None:
        self.installEventFilter(self)
        central = self.centralWidget()
        central.installEventFilter(self)
        for widget in central.findChildren(QWidget):
            widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() != QEvent.Type.KeyPress
                or not isinstance(event, QKeyEvent)
                or not self.isActiveWindow()):
            return super().eventFilter(watched, event)
        if event.modifiers() not in (Qt.KeyboardModifier.NoModifier,
                                     Qt.KeyboardModifier.ShiftModifier):
            return super().eventFilter(watched, event)
        focus = self.focusWidget()
        numeric_editor = self._parent_spin_box(focus)
        if isinstance(focus, (QLineEdit, QComboBox)) and numeric_editor is None:
            return super().eventFilter(watched, event)

        key = event.key()
        if numeric_editor is not None and key in (
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,):
            return super().eventFilter(watched, event)
        if key == Qt.Key.Key_X:
            if self._session is not None:
                self.settings_panel.show_mask.toggle()
            return True
        if key == Qt.Key.Key_R:
            self._run_preview()
            return True
        if key == Qt.Key.Key_Right:
            self._step_slider(self.frame_slider, 1)
            return True
        if key == Qt.Key.Key_Left:
            self._step_slider(self.frame_slider, -1)
            return True
        if key == Qt.Key.Key_Up:
            self._step_slider(self.z_slider, 1)
            return True
        if key == Qt.Key.Key_Down:
            self._step_slider(self.z_slider, -1)
            return True
        if key == Qt.Key.Key_C:
            self._next_channel()
            return True
        if key == Qt.Key.Key_S:
            self._apply_settings()
            return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _parent_spin_box(widget: QWidget | None) -> QAbstractSpinBox | None:
        while widget is not None:
            if isinstance(widget, QAbstractSpinBox):
                return widget
            widget = widget.parentWidget()
        return None

    @staticmethod
    def _step_slider(slider: QSlider, step: int) -> None:
        if slider.isEnabled():
            slider.setValue(slider.value() + step)

    def _next_channel(self) -> None:
        if self.channel_combo.isEnabled() and self.channel_combo.count() > 0:
            next_index = (self.channel_combo.currentIndex() + 1) % self.channel_combo.count()
            self.channel_combo.setCurrentIndex(next_index)

    @staticmethod
    def _navigation_control(label: str,
                            layout: QHBoxLayout,
                            ) -> tuple[QSlider, QLabel]:
        layout.addWidget(QLabel(label))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 0)
        layout.addWidget(slider, 1)
        value = QLabel("1 / 1")
        value.setMinimumWidth(60)
        layout.addWidget(value)
        return slider, value

    @Slot()
    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose experiments directory",
            self.directory_edit.text(),)
        if selected:
            self._set_experiments_directory(selected)

    def _set_experiments_directory(self, path: str | Path) -> None:
        raw_path = str(path).strip()
        resolved = Path(raw_path).expanduser().resolve() if raw_path else None
        if resolved is None or not resolved.is_dir():
            self.directory_edit.setText(raw_path)
            self.directory_browser.set_root("")
            self._close_session()
            self.status_label.setText("Choose an existing experiments directory.")
            return
        self.directory_edit.setText(str(resolved))
        self.status_label.setText("Select an experiment folder or its fits_array.tif file.")
        self.directory_browser.set_root(resolved)

    @Slot(object)
    def _path_selected(self, selected: object) -> None:
        if selected is None:
            return
        path = Path(selected)
        if path.is_dir():
            source = path / FITS_ARRAY_NAME
            if source.is_file() and self.directory_browser.select_path(source):
                return
        else:
            source = path
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
            self._session = SegmentationTuningSession(source, segment_settings=baseline)
        except Exception as error:
            self.status_label.setText(str(error))
            return
        self._source_path = source
        settings = self._session.segment_settings
        self.settings_panel.set_settings(settings)
        self.settings_panel.set_channels(self._session.channel_labels, settings.nuclear_channel)
        self.settings_panel.set_3d_available(self._session.plane_count > 1)
        self.channel_combo.clear()
        self.channel_combo.addItems(self._session.channel_labels)
        selected_channel = settings.channel_to_segment[0] if settings.channel_to_segment else None
        channel_index = self.channel_combo.findText(str(selected_channel))
        self.channel_combo.setCurrentIndex(max(channel_index, 0))
        self.frame_slider.setRange(0, self._session.frame_count - 1)
        self.z_slider.setRange(0, self._session.plane_count - 1)
        self.frame_slider.setValue(0)
        self.z_slider.setValue(0)
        self._set_source_controls_enabled(True)
        self._display_selection()
        self.status_label.setText(f"Loaded {source.parent.name} — axes {self._session.axes}, shape {self._session.shape}.")
        self._run_preview()

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

    @Slot()
    def _display_selection(self) -> None:
        if self._session is None or self.channel_combo.currentIndex() < 0:
            return
        frame = self.frame_slider.value()
        z_index = self.z_slider.value()
        channel = self.channel_combo.currentText()
        try:
            if self._displayed_channel is not None and self._displayed_channel != channel:
                self._channel_levels[self._displayed_channel] = self.image_viewer.display_levels
            self.image_viewer.set_channel_lut(channel)
            image = self._session.display_frame(frame, channel, z_index)
            self.image_viewer.set_image(image)
            if self._displayed_channel != channel:
                if channel in self._channel_levels:
                    self.image_viewer.set_display_levels(self._channel_levels[channel])
                else:
                    self.image_viewer.auto_scale()
                    self._channel_levels[channel] = self.image_viewer.display_levels
            self._displayed_channel = channel
            self.image_viewer.clear_mask()
            settings = self.current_settings()
            self._session.set_segment_settings(settings)
            cached = self._session.load_cached_preview(
                frame,
                channel,
                z_index,
                self.settings_panel.user_settings(),)
            if cached is not None:
                self._display_preview_mask(cached, z_index)
        except Exception as error:
            self.status_label.setText(str(error))
            return
        self.frame_value.setText(f"{frame + 1} / {self._session.frame_count}")
        self.z_value.setText(f"{z_index + 1} / {self._session.plane_count}")

    @Slot()
    def _run_preview(self) -> None:
        if self._session is None or self._thread is not None:
            return
        try:
            settings = self.current_settings()
            self._session.set_segment_settings(settings)
        except Exception as error:
            self.status_label.setText(f"Invalid Cellpose settings: {error}")
            return
        request = PreviewRequest(
            frame_index=self.frame_slider.value(),
            channel=self.channel_combo.currentText(),
            z_index=self.z_slider.value(),
            user_settings=self.settings_panel.user_settings(),)
        self._active_request = request
        self._thread = QThread(self)
        self._worker = PreviewWorker(self._session, request)
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
        self._thread = None
        self._worker = None
        self._active_request = None
        self._set_running(False)
        if thread is not None:
            thread.deleteLater()

    @Slot()
    def _apply_settings(self) -> None:
        try:
            settings = self.current_settings()
        except Exception as error:
            self.status_label.setText(f"Invalid Cellpose settings: {error}")
            return
        self._provided_settings = settings
        if self._session is not None:
            self._session.set_segment_settings(settings)
        self.settings_applied.emit(settings)
        self.status_label.setText("Current Cellpose settings applied.")

    def current_settings(self) -> SegmentSettings:
        """
        Return the complete validated settings represented by the viewer.
        """
        if self._session is None:
            raise RuntimeError("Load an experiment before applying settings.")
        payload: dict[str, Any] = self._session.segment_settings.model_dump()
        payload["channel_to_segment"] = [self.channel_combo.currentText()]
        payload["nuclear_channel"] = self.settings_panel.selected_nuclear_channel
        payload["do_denoise"] = self.settings_panel.denoise.isChecked()
        payload["user_settings"] = {
            **self._session.segment_settings.user_settings,
            **self.settings_panel.user_settings(),}
        return SegmentSettings.model_validate(payload)

    def _set_running(self, running: bool) -> None:
        self.progress.setVisible(running)
        self.settings_panel.set_running(running)
        self.directory_edit.setEnabled(not running)
        self.browse_button.setEnabled(not running)
        self.directory_browser.setEnabled(not running)
        self.frame_slider.setEnabled(not running)
        self.channel_combo.setEnabled(not running)
        self.z_slider.setEnabled(not running)

    def _set_source_controls_enabled(self, enabled: bool) -> None:
        self.settings_panel.setEnabled(enabled)
        self.frame_slider.setEnabled(enabled)
        self.channel_combo.setEnabled(enabled)
        self.z_slider.setEnabled(enabled)

    def _close_session(self) -> None:
        if self._session is not None:
            self._session.close()
        self._session = None
        self._source_path = None
        self._displayed_channel = None
        self._channel_levels.clear()
        self.image_viewer.image_item.clear()
        self.image_viewer.clear_mask()
        self.channel_combo.clear()
        self.frame_slider.setRange(0, 0)
        self.z_slider.setRange(0, 0)
        self.frame_value.setText("1 / 1")
        self.z_value.setText("1 / 1")
        self._set_source_controls_enabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            self.status_label.setText("Wait for the current Cellpose preview before closing.")
            event.ignore()
            return
        self._close_session()
        super().closeEvent(event)
