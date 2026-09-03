from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QColorDialog,
    QFileDialog,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from fits.environment.constant import FITS_ARRAY_NAME, FITS_REFERENCE_TEMPLATE, FITS_ROI_TEMPLATE
from fits.gui.run_browser import DirectoryBrowser
from fits.gui.settings_adapter import SAVED_SETTINGS_NAME, SettingsAdapter
from fits.gui.viewer.image_viewer import FitsImageViewer
from fits.gui.wheel_widgets import FocusWheelSlider
from fits.gui.viewer.tools.reference_mask.settings_panel import ReferenceMaskPanel
from fits.gui.viewer.tools.roi_mask.settings_panel import RoiMaskPanel
from fits.gui.viewer.tools.segmentation.settings_panel import CellposeSettingsPanel
from fits.gui.viewer.tools.segmentation.worker import PreviewOutcome, PreviewRequest, PreviewWorker
from fits.settings.models import SegmentSettings
from fits.tasks.reference_mask import ReferenceMaskSession
from fits.tasks.roi_mask import RoiSession
from fits.tasks.segmentation.preview_cache import SegmentationPreview
from fits.tasks.segmentation.tuning import SegmentationTuningSession


ViewerTool = Literal["segmentation", "binary", "all"]


class FitsViewerWindow(QMainWindow):
    """
    Browse FITS experiments, tune segmentation and draw reference masks.

    The window can run independently or be embedded in a FITS workflow. When
    Apply settings is clicked, ``settings_applied`` emits a complete validated
    ``SegmentSettings`` instance for the currently displayed channel. Switching
    tool tabs preserves both sessions; selecting another image replaces them.
    """

    settings_applied = Signal(object)

    def __init__(self,
                 experiments_dir: str | Path | None = None,
                 segment_settings: SegmentSettings | Mapping[str, Any] | None = None,
                 tool: ViewerTool = "segmentation",
                 parent: QWidget | None = None,
                 ) -> None:
        super().__init__(parent)
        if tool not in ("segmentation", "binary", "all"):
            raise ValueError(f"Unknown FITS viewer tool: {tool!r}.")
        self._visible_tool = tool
        self.setWindowTitle("FITS Viewer")
        self.resize(1700, 1150)

        self._provided_settings = (SegmentSettings.model_validate(segment_settings)
                                   if segment_settings is not None
                                   else None)
        self._segmentation_session: SegmentationTuningSession | None = None
        self._reference_session: ReferenceMaskSession | None = None
        self._roi_session: RoiSession | None = None
        self._source_path: Path | None = None
        self._reference_path: Path | None = None
        self._roi_path: Path | None = None
        self._thread: QThread | None = None
        self._worker: PreviewWorker | None = None
        self._active_request: PreviewRequest | None = None
        self._displayed_channel: str | None = None
        self._channel_levels: dict[str, tuple[float, float]] = {}

        self._build_ui()
        self._connect_signals()
        self._refresh_mask_colour_controls()
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
        file_filters = ((FITS_ARRAY_NAME,)
                        if self._visible_tool == "segmentation"
                        else (FITS_ARRAY_NAME,
                              FITS_REFERENCE_TEMPLATE.format(label="*"),
                              FITS_ROI_TEMPLATE.format(label="*")))
        self.directory_browser = DirectoryBrowser(
            "Experiments directory contents",
            file_name_filters=file_filters,)
        left_splitter.addWidget(self.directory_browser)

        self.settings_panel = CellposeSettingsPanel()
        self.reference_panel = ReferenceMaskPanel()
        self.roi_panel = RoiMaskPanel()
        self.settings_panel.overlay_widget.hide()
        self.reference_panel.overlay_widget.hide()
        self.roi_panel.overlay_widget.hide()
        self.tool_tabs = QTabWidget()
        if self._visible_tool in ("segmentation", "all"):
            self.tool_tabs.addTab(self.settings_panel, "Segmentation")
        if self._visible_tool in ("binary", "all"):
            self.tool_tabs.addTab(self.reference_panel, "Distance reference")
            self.tool_tabs.addTab(self.roi_panel, "ROI mask")
        left_splitter.addWidget(self.tool_tabs)
        left_splitter.setStretchFactor(0, 2)
        left_splitter.setStretchFactor(1, 6)
        left_splitter.setSizes([230, 750])
        left_layout.addWidget(left_splitter)
        main_splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_layout.addWidget(right_splitter)

        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(0, 0, 0, 0)
        info_row = QHBoxLayout()
        left_controls = QHBoxLayout()
        left_controls.addStretch(1)
        left_controls.addWidget(QLabel("Channel"))
        self.channel_combo = QComboBox()
        left_controls.addWidget(self.channel_combo)
        self.grayscale_lut_button = QPushButton("Grayscale")
        self.grayscale_lut_button.setCheckable(True)
        self.grayscale_lut_button.setToolTip(
            "Toggle grayscale display. Turn it off to restore the channel colour.")
        self.grayscale_lut_button.setStyleSheet(
            "QPushButton:checked { background-color: #2a82da; color: white; "
            "border: 1px solid #7fc0ff; }")
        left_controls.addWidget(self.grayscale_lut_button)
        left_controls.addStretch(1)
        info_row.addLayout(left_controls, 1)

        right_controls = QHBoxLayout()
        right_controls.addStretch(1)
        right_controls.addWidget(QLabel("Overlay"))
        self.show_mask = QCheckBox()
        self.show_mask.setChecked(True)
        self.show_mask.setToolTip("Show or hide the mask overlay.")
        right_controls.addWidget(self.show_mask)
        self.mask_opacity = FocusWheelSlider(Qt.Orientation.Horizontal)
        self.mask_opacity.setRange(0, 100)
        self.mask_opacity.setValue(45)
        self.mask_opacity.setMaximumWidth(140)
        self.mask_opacity.setToolTip("Adjust the opacity of the displayed mask overlay.")
        right_controls.addWidget(self.mask_opacity)
        self.segmentation_mask_colours = QLabel("Label palette")
        right_controls.addWidget(self.segmentation_mask_colours)
        self.reference_mask_colour = QColor(255, 215, 0)
        self.reference_mask_colour_button = QPushButton("Mask colour")
        self.reference_mask_colour_button.setToolTip(
            "Change the colour of the displayed binary mask.")
        self._set_reference_mask_colour_button()
        right_controls.addWidget(self.reference_mask_colour_button)
        right_controls.addStretch(1)
        info_row.addLayout(right_controls, 1)

        self.info_button = QToolButton()
        self.info_button.setText("i")
        self.info_button.setToolTip("Viewer information and keyboard shortcuts")
        self.info_button.setFixedSize(26, 26)
        self.info_button.setStyleSheet(
            "QToolButton { border: 1px solid #888; border-radius: 13px; "
            "font-weight: bold; font-style: italic; }")
        info_row.addWidget(self.info_button)
        image_layout.addLayout(info_row)
        self.image_viewer = FitsImageViewer()
        image_layout.addWidget(self.image_viewer, 1)
        navigation = QHBoxLayout()
        self.frame_slider, self.frame_value = self._navigation_control("Frame", navigation)
        self.z_slider, self.z_value = self._navigation_control("Z", navigation)
        image_layout.addLayout(navigation)
        right_splitter.addWidget(image_panel)

        lut_panel = QWidget()
        lut_layout = QHBoxLayout(lut_panel)
        lut_layout.setContentsMargins(0, 0, 0, 0)
        self.image_viewer.histogram.setMaximumHeight(125)
        self.image_viewer.histogram.setToolTip(
            "Adjust the displayed intensity range. Add a colour marker from the "
            "gradient menu; click a marker to edit its colour, or remove it from "
            "the colour dialog.")
        lut_layout.addWidget(self.image_viewer.histogram, 1)
        lut_actions = QVBoxLayout()
        self.auto_scale_button = QPushButton("Auto-scale")
        lut_actions.addWidget(self.auto_scale_button)
        self.full_range_button = QPushButton("Full range")
        lut_actions.addWidget(self.full_range_button)
        lut_actions.addStretch(1)
        lut_layout.addLayout(lut_actions)
        right_splitter.addWidget(lut_panel)
        right_splitter.setStretchFactor(0, 7)
        right_splitter.setStretchFactor(1, 1)
        right_splitter.setSizes([875, 125])
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
        self.reference_panel.drawing_options_changed.connect(
            self._update_drawing_options)
        self.reference_panel.undo_requested.connect(
            self._undo_reference_drawing)
        self.reference_panel.clear_requested.connect(
            self._clear_reference_drawing)
        self.reference_panel.save_requested.connect(
            self._save_reference_mask)
        self.reference_panel.mask_visibility_changed.connect(
            self.image_viewer.set_mask_visible)
        self.reference_panel.mask_opacity_changed.connect(
            self.image_viewer.set_mask_opacity)
        self.roi_panel.drawing_options_changed.connect(self._update_drawing_options)
        self.roi_panel.undo_requested.connect(self._undo_reference_drawing)
        self.roi_panel.clear_requested.connect(self._clear_reference_drawing)
        self.roi_panel.save_requested.connect(self._save_roi_mask)
        self.roi_panel.automatic_current_requested.connect(self._apply_otsu_threshold)
        self.roi_panel.automatic_stack_requested.connect(self._apply_otsu_stack)
        self.roi_panel.reset_current_requested.connect(self._reset_roi_current)
        self.roi_panel.reset_stack_requested.connect(self._reset_roi_stack)
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
        self.image_viewer.drawing_finished.connect(
            self._replace_reference_drawing)
        self.tool_tabs.currentChanged.connect(self._tool_changed)
        self.grayscale_lut_button.toggled.connect(
            lambda checked: self.image_viewer.set_coloured_lut(not checked))
        self.auto_scale_button.clicked.connect(self.image_viewer.auto_scale)
        self.full_range_button.clicked.connect(self.image_viewer.full_range)
        self.info_button.clicked.connect(self._show_information)
        self.reference_mask_colour_button.clicked.connect(
            self._choose_reference_mask_colour)
        self.show_mask.toggled.connect(self.image_viewer.set_mask_visible)
        self.mask_opacity.valueChanged.connect(
            lambda value: self.image_viewer.set_mask_opacity(value / 100.0))

    @Slot()
    def _show_information(self) -> None:
        fits_version = self._package_version("fits")
        kit_version = self._package_version("cellpose-kit")
        text = (
            "Browse normalized FITS experiments, inspect frames, channels and "
            "Z planes, and adjust image contrast. Tool tabs add focused image "
            "workflows. Segmentation previews Cellpose settings; binary tools "
            "create distance references and threshold-assisted ROI masks.\n\n"
            "Keyboard shortcuts\n"
            "X    Toggle mask overlay\n"
            "R    Run preview\n"
            "← / →    Previous / next frame\n"
            "↑ / ↓    Previous / next Z plane\n"
            "A / D    Previous / next frame\n"
            "W / Z    Next / previous Z plane\n"
            "C    Next channel\n"
            "S    Apply segmentation settings or save the active binary mask\n"
            "Ctrl + Z    Undo the latest binary-mask drawing\n"
            "Left mouse button    Add to a Reference or ROI mask\n"
            "Right mouse button    Erase from a Reference or ROI mask\n"
            "Ctrl + mouse drag    Pan image\n"
            "Ctrl + mouse wheel   Zoom image\n\n"
            f"FITS {fits_version}\n"
            f"cellpose-kit {kit_version}\n"
            f"{self.settings_panel.version_label.text()}")
        QMessageBox.information(self, "About FITS Viewer", text)

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
        focus = self.focusWidget()
        numeric_editor = self._parent_spin_box(focus)
        key = event.key()
        if isinstance(focus, QLineEdit) and numeric_editor is None:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                QTimer.singleShot(0, self.image_viewer.setFocus)
            return super().eventFilter(watched, event)

        if (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and key == Qt.Key.Key_Z
                and self._binary_tool_active()):
            self._undo_reference_drawing()
            return True
        if event.modifiers() not in (Qt.KeyboardModifier.NoModifier,
                                     Qt.KeyboardModifier.ShiftModifier):
            return super().eventFilter(watched, event)
        if numeric_editor is not None and key in (
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,):
            return super().eventFilter(watched, event)
        if key == Qt.Key.Key_X:
            if self._segmentation_session is not None:
                self.show_mask.toggle()
            return True
        if key == Qt.Key.Key_R:
            if not self._binary_tool_active():
                self._run_preview()
            return True
        if key in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self._step_slider(self.frame_slider, 1)
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self._step_slider(self.frame_slider, -1)
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_W):
            self._step_slider(self.z_slider, 1)
            return True
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Z):
            self._step_slider(self.z_slider, -1)
            return True
        if key == Qt.Key.Key_C:
            self._next_channel()
            return True
        if key == Qt.Key.Key_S:
            if self._reference_tool_active():
                self._save_reference_mask()
            elif self._roi_tool_active():
                self._save_roi_mask()
            else:
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
        if (source == self._source_path and reference_path == self._reference_path
                and roi_path == self._roi_path):
            return
        if self._thread is not None:
            self.status_label.setText("Wait for the current preview before changing experiment.")
            return
        self._close_session()
        try:
            baseline = self._settings_for_source(source)
            self._segmentation_session = SegmentationTuningSession(
                source, segment_settings=baseline)
            self._reference_session = ReferenceMaskSession(
                source, reference_path=reference_path)
            self._roi_session = RoiSession(source, roi_path=roi_path)
        except Exception as error:
            if self._segmentation_session is not None:
                self._segmentation_session.close()
            self._segmentation_session = None
            self._reference_session = None
            self._roi_session = None
            self.status_label.setText(str(error))
            return
        self._source_path = source
        self._reference_path = reference_path
        self._roi_path = roi_path
        settings = self._segmentation_session.segment_settings
        self.settings_panel.set_settings(settings)
        self.settings_panel.set_channels(
            self._segmentation_session.channel_labels, settings.nuclear_channel)
        self.settings_panel.set_3d_available(
            self._segmentation_session.plane_count > 1)
        self.reference_panel.set_available_axes(
            self._reference_session.axes, self._reference_session.shape)
        self.roi_panel.set_available_axes(
            self._roi_session.axes, self._roi_session.shape)
        self.channel_combo.clear()
        self.channel_combo.addItems(self._segmentation_session.channel_labels)
        selected_channel = settings.channel_to_segment[0] if settings.channel_to_segment else None
        if self._reference_session.loaded_channels:
            selected_channel = self._reference_session.loaded_channels[0]
        if self._roi_session.loaded_channels:
            selected_channel = self._roi_session.loaded_channels[0]
        channel_index = self.channel_combo.findText(str(selected_channel))
        self.channel_combo.setCurrentIndex(max(channel_index, 0))
        self.frame_slider.setRange(0, self._segmentation_session.frame_count - 1)
        self.z_slider.setRange(0, self._segmentation_session.plane_count - 1)
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
            f"{self._segmentation_session.axes}, shape {self._segmentation_session.shape}.")
        if self._segmentation_tool_active():
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
        if self._segmentation_session is None or self.channel_combo.currentIndex() < 0:
            return
        frame = self.frame_slider.value()
        z_index = self.z_slider.value()
        channel = self.channel_combo.currentText()
        try:
            if self._displayed_channel is not None and self._displayed_channel != channel:
                self._channel_levels[self._displayed_channel] = self.image_viewer.display_levels
            self.image_viewer.set_channel_lut(channel)
            image = self._segmentation_session.display_frame(frame, channel, z_index)
            self.image_viewer.set_image(image)
            if self._displayed_channel != channel:
                if channel in self._channel_levels:
                    self.image_viewer.set_display_levels(self._channel_levels[channel])
                else:
                    self.image_viewer.auto_scale()
                    self._channel_levels[channel] = self.image_viewer.display_levels
            self._displayed_channel = channel
            self.image_viewer.clear_mask()
            if self._binary_tool_active():
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
                if self._roi_tool_active():
                    self.roi_panel.set_threshold_image(image)
                    threshold_range = self._roi_session.threshold_range(
                        frame_index=frame, channel=channel, z_index=z_index)
                    if threshold_range is not None:
                        self.roi_panel.set_threshold_range(*threshold_range)
            else:
                self.image_viewer.set_drawing_enabled(False)
                settings = self.current_settings()
                self._segmentation_session.set_segment_settings(settings)
                cached = self._segmentation_session.load_cached_preview(
                    frame,
                    channel,
                    z_index,
                    self.settings_panel.user_settings(),)
                if cached is not None:
                    self._display_preview_mask(cached, z_index)
                self.image_viewer.set_mask_visible(self.show_mask.isChecked())
                self.image_viewer.set_mask_opacity(self.mask_opacity.value() / 100.0)
        except Exception as error:
            self.status_label.setText(str(error))
            return
        self.frame_value.setText(
            f"{frame + 1} / {self._segmentation_session.frame_count}")
        self.z_value.setText(
            f"{z_index + 1} / {self._segmentation_session.plane_count}")

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

    def _segmentation_tool_active(self) -> bool:
        return self.tool_tabs.currentWidget() is self.settings_panel

    @Slot()
    def _disable_active_interpolation_preview(self) -> None:
        panel = self._active_binary_panel()
        if panel is not None and panel.live_preview.isChecked():
            panel.live_preview.setChecked(False)

    @staticmethod
    def _binary_display_mask(
            session: ReferenceMaskSession | RoiSession,
            panel: ReferenceMaskPanel | RoiMaskPanel,
            frame_index: int, channel: str, z_index: int) -> NDArray[np.uint8]:
        axis = panel.preview_interpolation_axis
        if panel.interpolation_preview_enabled and axis is not None:
            options = dict(
                frame_index=frame_index, channel=channel, z_index=z_index,
                extrapolate_start=panel.extrapolate_start.isChecked(),
                extrapolate_end=panel.extrapolate_end.isChecked())
            if isinstance(session, RoiSession):
                return session.interpolated_display_mask_plane(axis, **options)
            return session.interpolated_mask_plane(axis, **options)
        if isinstance(session, RoiSession):
            return session.display_mask_plane(frame_index, channel, z_index)
        return session.mask_plane(frame_index, channel, z_index)

    def _set_tool_enabled(self, panel: QWidget, enabled: bool) -> None:
        index = self.tool_tabs.indexOf(panel)
        if index >= 0:
            self.tool_tabs.setTabEnabled(index, enabled)

    @Slot(int)
    def _tool_changed(self, _: int) -> None:
        self._refresh_mask_colour_controls()
        self._update_drawing_options()
        self._display_selection()

    def _refresh_mask_colour_controls(self) -> None:
        binary = self._binary_tool_active()
        self.segmentation_mask_colours.setVisible(not binary)
        self.reference_mask_colour_button.setVisible(binary)
        self.image_viewer.set_mask_color(
            self.reference_mask_colour if binary else None)

    def _set_reference_mask_colour_button(self) -> None:
        color = self.reference_mask_colour.name()
        self.reference_mask_colour_button.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: black; }}")

    @Slot()
    def _choose_reference_mask_colour(self) -> None:
        selected = QColorDialog.getColor(
            self.reference_mask_colour, self, "Reference mask colour")
        if not selected.isValid():
            return
        self.reference_mask_colour = selected
        self._set_reference_mask_colour_button()
        if self._binary_tool_active():
            self.image_viewer.set_mask_color(selected)

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
            coordinates = dict(
                frame_index=self.frame_slider.value(),
                channel=self.channel_combo.currentText(),
                z_index=self.z_slider.value())
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

    @Slot()
    def _undo_reference_drawing(self) -> None:
        session = self._active_binary_session()
        panel = self._active_binary_panel()
        if session is None or panel is None:
            return
        coordinates = dict(frame_index=self.frame_slider.value(),
                           channel=self.channel_combo.currentText(),
                           z_index=self.z_slider.value())
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
    def _save_reference_mask(self) -> None:
        if self._reference_session is None:
            return
        try:
            label = self.reference_panel.reference_label
            channel = self.channel_combo.currentText()
            self._reference_session.set_mask_plane(
                self.image_viewer.drawing_mask,
                frame_index=self.frame_slider.value(),
                channel=channel,
                z_index=self.z_slider.value(),)
            saved_channels = self._reference_session.saved_channels(label)
            if saved_channels and channel not in saved_channels:
                QMessageBox.information(
                    self,
                    "Add reference channel",
                    f"{FITS_REFERENCE_TEMPLATE.format(label=label)} already "
                    f"contains {', '.join(saved_channels)}. The {channel} "
                    "reference channel will be added to the same file.")
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

    @Slot()
    def _apply_otsu_threshold(self) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        try:
            image = self._segmentation_session.display_frame(
                self.frame_slider.value(), self.channel_combo.currentText(),
                self.z_slider.value()) if self._segmentation_session is not None else None
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

    @Slot()
    def _reset_roi_current(self) -> None:
        if self._roi_session is None:
            return
        self._disable_active_interpolation_preview()
        self._roi_session.clear_mask_plane(
            frame_index=self.frame_slider.value(), channel=self.channel_combo.currentText(),
            z_index=self.z_slider.value())
        self.image_viewer.set_drawing_mask(
            self._roi_session.display_mask_plane(
                self.frame_slider.value(), self.channel_combo.currentText(),
                self.z_slider.value()))
        self.status_label.setText("Removed the ROI mask from the current plane.")

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
    def _reset_roi_stack(self) -> None:
        if self._roi_session is None:
            return
        self._disable_active_interpolation_preview()
        self._roi_session.clear_stack(channel=self.channel_combo.currentText())
        self._display_selection()
        self.status_label.setText(
            f"Removed ROI masks from the complete {self.channel_combo.currentText()} stack.")

    @Slot()
    def _fill_roi_holes(self) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        coordinates = dict(
            frame_index=self.frame_slider.value(),
            channel=self.channel_combo.currentText(),
            z_index=self.z_slider.value())
        try:
            changed = self._roi_session.fill_holes(**coordinates)
            self.image_viewer.set_drawing_mask(
                self._roi_session.display_mask_plane(**coordinates))
            self.roi_panel.set_undo_available(changed)
            self.status_label.setText(
                "Filled enclosed holes on the current ROI plane."
                if changed else "The current ROI plane contains no enclosed holes.")
        except Exception as error:
            self.status_label.setText(f"Could not fill ROI holes: {error}")

    @Slot(int)
    def _remove_small_roi_objects(self, minimum_size: int) -> None:
        if self._roi_session is None or not self._roi_tool_active():
            return
        self._disable_active_interpolation_preview()
        coordinates = dict(
            frame_index=self.frame_slider.value(),
            channel=self.channel_combo.currentText(),
            z_index=self.z_slider.value())
        try:
            changed = self._roi_session.remove_small_objects(
                minimum_size, **coordinates)
            self.image_viewer.set_drawing_mask(
                self._roi_session.display_mask_plane(**coordinates))
            self.roi_panel.set_undo_available(changed)
            self.status_label.setText(
                f"Removed ROI objects smaller than {minimum_size} px² "
                "from the current plane."
                if changed else
                f"No ROI objects smaller than {minimum_size} px² were found.")
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
        if self._segmentation_session is not None:
            self._segmentation_session.set_segment_settings(settings)
        self.settings_applied.emit(settings)
        self.status_label.setText("Current Cellpose settings applied.")

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

    def _set_running(self, running: bool) -> None:
        self.progress.setVisible(running)
        self.settings_panel.set_running(running)
        self._set_tool_enabled(self.reference_panel, not running)
        self._set_tool_enabled(self.roi_panel, not running)
        self.directory_edit.setEnabled(not running)
        self.browse_button.setEnabled(not running)
        self.directory_browser.setEnabled(not running)
        self.frame_slider.setEnabled(not running)
        self.channel_combo.setEnabled(not running)
        self.z_slider.setEnabled(not running)

    def _set_source_controls_enabled(self, enabled: bool) -> None:
        self.settings_panel.setEnabled(enabled)
        self.reference_panel.setEnabled(enabled)
        self.roi_panel.setEnabled(enabled)
        self.frame_slider.setEnabled(enabled)
        self.channel_combo.setEnabled(enabled)
        self.z_slider.setEnabled(enabled)

    def _close_session(self) -> None:
        if self._segmentation_session is not None:
            self._segmentation_session.close()
        self._segmentation_session = None
        self._reference_session = None
        self._roi_session = None
        self._source_path = None
        self._reference_path = None
        self._roi_path = None
        self._displayed_channel = None
        self._channel_levels.clear()
        self.image_viewer.image_item.clear()
        self.image_viewer.clear_mask()
        self.image_viewer.set_drawing_enabled(False)
        self.reference_panel.set_undo_available(False)
        self.roi_panel.set_undo_available(False)
        self.reference_panel.label_edit.clear()
        self.roi_panel.label_edit.clear()
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
