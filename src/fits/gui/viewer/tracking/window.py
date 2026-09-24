from __future__ import annotations

from pathlib import Path
import colorsys

import numpy as np
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor, QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from fits.environment.constant import (
    FITS_ARRAY_NAME,
    FITS_MASK_TRACK,
    FITS_MASK_TRACK_EDITED,
    FITS_MASK_TRACK_EDITED_FILTERED,
)
from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.segmentation.diameter_reference import DiameterReference
from fits.gui.viewer.tracking.session import TrackingViewerSession
from fits.gui.viewer.tracking.path_item import TrackPathsItem
from fits.workflows.runtime.interactive.messages import (
    TrackEditOutcome, TrackEditRequest)


class _SaveWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, session: TrackingViewerSession, options: dict) -> None:
        super().__init__()
        self.session = session
        self.options = options

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.session.save_rendered_display(**self.options))
        except Exception as error:
            self.failed.emit(str(error))


class _LocalSegmentationWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, session: TrackingViewerSession, options: dict) -> None:
        super().__init__()
        self.session = session
        self.options = options

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.session.preview_add_edit(**self.options))
        except Exception as error:
            self.failed.emit(str(error))


class _TrackingSaveWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, session: TrackingViewerSession, options: dict) -> None:
        super().__init__()
        self.session = session
        self.options = options

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.session.save_edited_tracking(**self.options))
        except Exception as error:
            self.failed.emit(str(error))


class _ColorSwatchButton(QPushButton):
    left_selected = Signal(object)
    right_selected = Signal(object)

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(34, 26)
        self.setToolTip(
            "Left-click: active mask color. Right-click: other masks color.")
        self.setStyleSheet(
            f"background-color: {self.color.name()}; border: 1px solid #777;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.right_selected.emit(self.color)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.left_selected.emit(self.color)
        super().mousePressEvent(event)


class _MaskColorDialog(QDialog):
    """Choose both mask-edit colors from one left/right-click palette."""

    def __init__(self, active: QColor, other: QColor,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.active_color = QColor(active)
        self.other_color = QColor(other)
        self.setWindowTitle("Choose mask edit colors")
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Left-click a color for the active inner mask. Right-click a color "
            "for the surrounding outer masks.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.preview = QPushButton("Active mask / other masks")
        self.preview.setEnabled(False)
        layout.addWidget(self.preview)

        palette = QGridLayout()
        colors = [
            QColor("black"), QColor("white"), QColor("lightgray"), QColor("gray"),
            *[QColor.fromHsv(hue, saturation, value)
              for value in (255, 190)
              for saturation in (110, 210)
              for hue in range(0, 360, 45)],
        ]
        for index, color in enumerate(colors):
            swatch = _ColorSwatchButton(color, self)
            swatch.left_selected.connect(self._set_active)
            swatch.right_selected.connect(self._set_other)
            palette.addWidget(swatch, index // 8, index % 8)
        layout.addLayout(palette)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_preview()

    @Slot(object)
    def _set_active(self, color: QColor) -> None:
        self.active_color = QColor(color)
        self._update_preview()

    @Slot(object)
    def _set_other(self, color: QColor) -> None:
        self.other_color = QColor(color)
        self._update_preview()

    def _update_preview(self) -> None:
        self.preview.setStyleSheet(
            f"background-color: {self.active_color.name()}; "
            f"border: 7px solid {self.other_color.name()}; "
            "color: black; padding: 8px;")


class TrackingViewerWindow(ImageToolWindow):
    """Initial tracked-label movie viewer; editing controls will follow."""

    tracking_finalized = Signal(object)

    file_filters = (FITS_MASK_TRACK, FITS_ARRAY_NAME)
    tool_help = (
        "\nTracking editor\n"
        "Ctrl + click mask or centroid    Select track\n"
        "Ctrl + click selected track    Unselect track\n"
        "S    Accept current Split or Add/Edit preview\n"
        "Split mode: Ctrl + click a cell, then click where the division should "
        "pass or drag along the proposed split line. Stroke pixels outside the "
        "selected mask are ignored.\n"
        "Add/Edit: left click predicts/adds; right click predicts/removes; "
        "dragging uses the literal brush.\n")

    def __init__(self, experiments_dir: str | Path | None = None,
                 tracking_path: str | Path | None = None,
                 parent: QWidget | None = None,
                 *, editing_enabled: bool = True,
                 pipeline_request: TrackEditRequest | None = None) -> None:
        self.editing_enabled = editing_enabled
        self._pipeline_request = pipeline_request
        self._pipeline_resolved = False
        if not editing_enabled:
            self.file_filters = (FITS_MASK_TRACK,)
        self._tracking_session: TrackingViewerSession | None = None
        self._track_path_items: list[TrackPathsItem] = []
        self._save_thread: QThread | None = None
        self._save_worker: _SaveWorker | None = None
        self._tracking_save_thread: QThread | None = None
        self._tracking_save_worker: _TrackingSaveWorker | None = None
        self._selected_track_ids: list[int] = []
        self._split_preview: dict[str, object] | None = None
        self._local_segmentation_preview: dict[str, object] | None = None
        self._local_segmentation_thread: QThread | None = None
        self._local_segmentation_worker: _LocalSegmentationWorker | None = None
        self._positive_points: list[tuple[int, int]] = []
        self._negative_points: list[tuple[int, int]] = []
        self._collect_local_prompts = False
        self._local_segmentation_context: tuple[int, int, int] | None = None
        self._local_target_track_id: int | None = None
        self._local_target_is_new = False
        self._manual_excluded_mask: np.ndarray | None = None
        self._path_color = QColor(255, 215, 0)
        self._other_mask_color = QColor(235, 235, 235)
        self._active_mask_color = QColor(255, 235, 0)
        self.raw_image_toggle = QCheckBox("Display raw image")
        self.raw_image_toggle.setChecked(True)
        self.raw_image_toggle.setToolTip(
            "Show or hide the selected channel from the sibling fits_array.tif image.")
        super().__init__(experiments_dir, parent)
        self.setWindowTitle(
            "FITS Tracking Viewer / Editor" if editing_enabled else "FITS Tracking Viewer")
        self.left_display_controls.insertWidget(0, self.raw_image_toggle)
        self.left_display_controls.insertSpacing(1, 10)
        self.overlay_label.setText("Mask overlay")
        if not editing_enabled:
            self.track_edit_section.hide()
            self.mask_edit_section.hide()
            self.local_cell_diameter.hide()
        if tracking_path is not None:
            self._path_selected(Path(tracking_path))

    def _build_tools(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        display_section, display = self._section("Display settings")
        tracks_row = QHBoxLayout()
        self.show_track_paths = QCheckBox("Show track paths")
        self.show_track_paths.setChecked(True)
        tracks_row.addWidget(self.show_track_paths)
        tracks_row.addStretch(1)
        tracks_row.addWidget(QLabel("Thickness"))
        self.path_thickness = QSpinBox()
        self.path_thickness.setRange(1, 12)
        self.path_thickness.setValue(2)
        self.path_thickness.setSuffix(" px")
        tracks_row.addWidget(self.path_thickness)
        display.addLayout(tracks_row)

        history_row = QHBoxLayout()
        history_row.addWidget(QLabel("Path extent"))
        self.path_extent = QComboBox()
        self.path_extent.addItem("Build to current frame", "built")
        self.path_extent.addItem("Show full path", "full")
        history_row.addWidget(self.path_extent, 1)
        display.addLayout(history_row)
        display.addSpacing(9)

        centroid_row = QHBoxLayout()
        self.show_centroids = QCheckBox("Show centroid markers")
        self.show_centroids.setChecked(True)
        centroid_row.addWidget(self.show_centroids)
        centroid_row.addStretch(1)
        centroid_row.addWidget(QLabel("Size"))
        self.centroid_size = QSpinBox()
        self.centroid_size.setRange(1, 30)
        self.centroid_size.setValue(5)
        self.centroid_size.setSuffix(" px")
        centroid_row.addWidget(self.centroid_size)
        display.addLayout(centroid_row)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Colors"))
        self.path_color_mode = QComboBox()
        self.path_color_mode.addItem("Match track palette", "track")
        self.path_color_mode.addItem("Single color", "single")
        color_row.addWidget(self.path_color_mode, 1)
        self.path_color_button = QPushButton("Center Color")
        self.path_color_button.setToolTip(
            "Used only when Colors is set to Single color; it changes paths and centroids.")
        self._update_path_color_button()
        self.path_color_button.hide()
        color_row.addWidget(self.path_color_button)
        display.addLayout(color_row)
        layout.addWidget(display_section)

        filter_section, filters = self._section("Track filtering")
        self.filter_tracks = QCheckBox("Filter by track length")
        self.filter_tracks.setToolTip(
            "Track length is the number of frames in which that track appears.")
        filters.addWidget(self.filter_tracks)
        filter_row = QHBoxLayout()
        self.filter_operator = QComboBox()
        for label, value in (("Lower than", "lt"), ("Lower or equal", "le"),
                             ("Equal", "eq"), ("Not equal", "ne"),
                             ("Greater or equal", "ge"), ("Greater than", "gt"),
                             ("Between (inclusive)", "between")):
            self.filter_operator.addItem(label, value)
        self.filter_operator.setCurrentIndex(self.filter_operator.findData("ge"))
        filter_row.addWidget(self.filter_operator, 1)
        self.filter_value = QSpinBox()
        self.filter_value.setRange(1, 1_000_000)
        self.filter_value.setValue(100)
        self.filter_value.setSuffix(" frames")
        filter_row.addWidget(self.filter_value)
        self.filter_maximum = QSpinBox()
        self.filter_maximum.setRange(1, 1_000_000)
        self.filter_maximum.setValue(200)
        self.filter_maximum.setSuffix(" frames")
        self.filter_maximum.hide()
        filter_row.addWidget(self.filter_maximum)
        filters.addLayout(filter_row)
        layout.addWidget(filter_section)

        track_section, track_editing = self._section("Track operations")
        self.track_edit_section = track_section
        instructions = QLabel(
            "Ctrl+click a mask or centroid to select it; Ctrl+click it again to unselect. "
            "Edits remain in memory.")
        instructions.setWordWrap(True)
        track_editing.addWidget(instructions)
        self.track_selection_label = QLabel("Selected tracks: none")
        track_editing.addWidget(self.track_selection_label)
        edit_row = QHBoxLayout()
        self.merge_tracks_button = QPushButton("Merge from this frame")
        self.merge_tracks_button.setToolTip(
            "Combine two selected tracks from the current frame onward.")
        edit_row.addWidget(self.merge_tracks_button)
        self.link_tracks_button = QPushButton("Link histories")
        self.link_tracks_button.setToolTip(
            "Join two selected track histories across the complete movie.")
        edit_row.addWidget(self.link_tracks_button)
        self.stop_track_button = QPushButton("Stop after this frame")
        self.stop_track_button.setToolTip(
            "End one selected track here and assign its later masks a new ID.")
        edit_row.addWidget(self.stop_track_button)
        track_editing.addLayout(edit_row)
        self.clear_track_selection_button = QPushButton("Clear selection")
        track_editing.addWidget(self.clear_track_selection_button)
        layout.addWidget(track_section)

        mask_section, mask_editing = self._section("Mask editing")
        self.mask_edit_section = mask_section
        split_row = QHBoxLayout()
        self.preview_split_button = QCheckBox("Split mode")
        self.preview_split_button.setToolTip(
            "Automatically find a narrow neck, with a balanced watershed fallback.")
        split_row.addWidget(self.preview_split_button)
        self.apply_split_button = QPushButton("Accept split")
        self.apply_split_button.setToolTip("Apply the displayed split to this frame.")
        split_row.addWidget(self.apply_split_button)
        self.cancel_split_button = QPushButton("Cancel preview")
        split_row.addWidget(self.cancel_split_button)
        mask_editing.addLayout(split_row)
        mask_editing.addSpacing(8)
        local_row = QHBoxLayout()
        self.add_mask_button = QCheckBox("Add / edit masks mode")
        self.add_mask_button.setToolTip(
            "Create a new mask, or edit the selected track's mask across frames.")
        local_row.addWidget(self.add_mask_button)
        self.accept_mask_button = QPushButton("Accept mask")
        local_row.addWidget(self.accept_mask_button)
        self.cancel_mask_button = QPushButton("Cancel current mask")
        local_row.addWidget(self.cancel_mask_button)
        mask_editing.addLayout(local_row)
        mask_editing.addSpacing(8)
        self.delete_mask_button = QPushButton("Delete selected mask")
        self.delete_mask_button.setToolTip(
            "Remove the selected track's mask from this frame only.")
        mask_editing.addWidget(self.delete_mask_button)
        mask_editing.addSpacing(8)
        brush_row = QHBoxLayout()
        brush_row.addWidget(QLabel("Brush size"))
        self.local_brush_size = QSpinBox()
        self.local_brush_size.setRange(1, 101)
        self.local_brush_size.setSingleStep(2)
        self.local_brush_size.setValue(5)
        self.local_brush_size.setSuffix(" px")
        brush_row.addWidget(self.local_brush_size)
        self.mask_edit_colors_button = QPushButton("Mask edit colors")
        self.mask_edit_colors_button.setToolTip(
            "Outer border: other masks. Inner fill: the mask being edited.")
        self._update_mask_edit_colors_button()
        brush_row.addWidget(self.mask_edit_colors_button)
        brush_row.addStretch(1)
        mask_editing.addLayout(brush_row)
        self.local_segmentation_help = QLabel(
            "Click for automatic prediction: left adds foreground, right removes it. "
            "Drag to add or erase. Press S to accept Split or Add/Edit previews. "
            "Ctrl+click a mask or centroid to select or unselect its track. "
            "In the color window, left-click sets the active mask and right-click sets others.")
        self.local_segmentation_help.setWordWrap(True)
        mask_editing.addWidget(self.local_segmentation_help)
        self.local_cell_diameter = QSpinBox()
        self.local_cell_diameter.setRange(4, 1000)
        self.local_cell_diameter.setValue(40)
        self.local_cell_diameter.setPrefix("Ø ")
        self.local_cell_diameter.setSuffix(" px")
        self.local_cell_diameter.setToolTip(
            "Approximate cell diameter. Used for cold-start segmentation; the circle "
            "shows this size in image pixels.")
        self.local_cell_diameter.setEnabled(False)
        layout.addWidget(mask_section)
        layout.addStretch(1)
        self.tool_panel = panel
        return panel

    @staticmethod
    def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("settingsSection")
        frame.setStyleSheet(
            "QFrame#settingsSection { background-color: #303030; "
            "border: 1px solid #555; border-radius: 4px; }")
        section_layout = QVBoxLayout(frame)
        section_layout.setContentsMargins(9, 7, 9, 9)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: bold; border: none;")
        section_layout.addWidget(heading)
        return frame, section_layout

    def _build_viewer_actions(self, layout: QHBoxLayout) -> None:
        layout.addSpacing(24)
        if not self.editing_enabled:
            section, saving = self._section("Save current display")
            row = QHBoxLayout()
            row.addWidget(QLabel("Optional label"))
            self.display_label_edit = QLineEdit()
            self.display_label_edit.setPlaceholderText("Optional")
            row.addWidget(self.display_label_edit, 1)
            self.save_display_button = QPushButton("Save current display")
            self.save_display_button.setEnabled(False)
            self.save_display_button.setToolTip(
                "Save an RGB rendering of the masks, paths, and optional raw image.")
            row.addWidget(self.save_display_button)
            saving.addLayout(row)
            layout.addWidget(section, 1, Qt.AlignmentFlag.AlignVCenter)
        if self._pipeline_request is not None:
            finalize_section, finalize = self._section("Finish tracking edit")
            finalize_row = QHBoxLayout()
            self.save_tracking_button = QPushButton("Save edited tracking")
            self.save_tracking_button.setEnabled(False)
            self.save_tracking_button.setToolTip(
                "Save a label-mask copy and make it the active downstream tracking artifact.")
            finalize_row.addWidget(self.save_tracking_button)
            self.use_original_button = QPushButton("Use original tracking")
            self.use_original_button.setToolTip(
                "Finish this edit step without changing the active tracking artifact.")
            finalize_row.addWidget(self.use_original_button)
            finalize.addLayout(finalize_row)
            layout.addWidget(finalize_section, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(24)

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        self.track_palette_label = QLabel("Track palette")
        layout.addWidget(self.track_palette_label)
        layout.addSpacing(12)
        layout.addWidget(QLabel("Mask channel"))
        self.mask_channel_combo = QComboBox()
        self.mask_channel_combo.setToolTip(
            "Choose the tracked-label channel independently from the raw image channel.")
        layout.addWidget(self.mask_channel_combo)

    def _connect_tools(self) -> None:
        self.local_cell_diameter.setParent(self.image_viewer.canvas)
        self.local_cell_diameter.setFixedSize(105, 30)
        self.local_cell_diameter.move(44, 8)
        self.local_cell_diameter.setStyleSheet(
            "QSpinBox { background: rgba(35, 35, 35, 215); color: #e8edf2; "
            "border: 1px solid #777; border-radius: 4px; padding: 2px 5px; }")
        self.local_cell_diameter.raise_()
        self.diameter_reference = DiameterReference(
            self.image_viewer.view_box, self.image_viewer.image_item)
        self.local_cell_diameter.valueChanged.connect(
            self.diameter_reference.set_diameter)
        self.diameter_reference.set_diameter(self.local_cell_diameter.value())
        self.raw_image_toggle.toggled.connect(self.image_viewer.image_item.setVisible)
        self.mask_channel_combo.currentIndexChanged.connect(self._display_selection)
        self.show_track_paths.toggled.connect(self._display_track_paths)
        self.path_extent.currentIndexChanged.connect(self._display_track_paths)
        self.path_thickness.valueChanged.connect(self._display_track_paths)
        self.path_color_mode.currentIndexChanged.connect(self._path_color_mode_changed)
        self.show_centroids.toggled.connect(self._display_track_paths)
        self.show_centroids.toggled.connect(self.centroid_size.setEnabled)
        self.centroid_size.valueChanged.connect(self._display_track_paths)
        self.filter_tracks.toggled.connect(self._filter_changed)
        self.filter_operator.currentIndexChanged.connect(self._filter_changed)
        self.filter_value.valueChanged.connect(self._filter_value_changed)
        self.filter_maximum.valueChanged.connect(self._display_selection)
        self.path_color_button.clicked.connect(self._choose_path_color)
        self.mask_edit_colors_button.clicked.connect(self._choose_mask_edit_colors)
        if not self.editing_enabled:
            self.save_display_button.clicked.connect(self._save_current_display)
        if self._pipeline_request is not None:
            self.save_tracking_button.clicked.connect(self._save_edited_tracking)
            self.use_original_button.clicked.connect(self._use_original_tracking)
        self.image_viewer.canvas.scene().sigMouseClicked.connect(
            self._tracking_scene_clicked)
        self.merge_tracks_button.clicked.connect(self._merge_selected_tracks)
        self.link_tracks_button.clicked.connect(self._link_selected_tracks)
        self.stop_track_button.clicked.connect(self._stop_selected_track)
        self.clear_track_selection_button.clicked.connect(self._clear_track_selection)
        self.preview_split_button.toggled.connect(self._toggle_split_mode)
        self.apply_split_button.clicked.connect(self._apply_previewed_split)
        self.cancel_split_button.clicked.connect(self._cancel_split_preview)
        self.delete_mask_button.clicked.connect(self._delete_selected_mask)
        self.add_mask_button.toggled.connect(self._toggle_local_segmentation_mode)
        self.accept_mask_button.clicked.connect(self._accept_local_segmentation)
        self.cancel_mask_button.clicked.connect(self._cancel_local_segmentation)
        self.local_brush_size.valueChanged.connect(self._configure_local_drawing)
        self.image_viewer.drawing_finished.connect(self._local_drawing_finished)
        self._filter_changed()
        self._update_edit_buttons()

    @Slot()
    def _filter_value_changed(self) -> None:
        self.filter_maximum.setMinimum(self.filter_value.value())
        self._display_selection()

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key.Key_S and self._split_preview is not None:
            self._apply_previewed_split()
            return True
        if (event.key() == Qt.Key.Key_S
                and self._collect_local_prompts
                and self._local_segmentation_preview is not None
                and self._local_segmentation_thread is None):
            self._accept_local_segmentation()
            return True
        return False

    @Slot(object)
    def _path_selected(self, selected: object) -> None:
        if not isinstance(selected, (str, Path)):
            return
        source = Path(selected)
        if source.is_dir():
            tracking_candidates = (
                source / FITS_MASK_TRACK_EDITED_FILTERED,
                source / FITS_MASK_TRACK_EDITED,
                source / FITS_MASK_TRACK,
            )
            track_source = next(
                (path for path in tracking_candidates if path.is_file()),
                source / FITS_MASK_TRACK,
            )
            image_source = source / FITS_ARRAY_NAME
            source = track_source if track_source.is_file() else image_source
            if source.is_file() and self.directory_browser.select_path(source):
                return
        if source.name not in {
                FITS_MASK_TRACK,
                FITS_MASK_TRACK_EDITED,
                FITS_MASK_TRACK_EDITED_FILTERED,
                FITS_ARRAY_NAME} or not source.is_file():
            self.status_label.setText(
                f"Select an experiment containing {FITS_MASK_TRACK} or {FITS_ARRAY_NAME}.")
            return
        self._open_source(source)

    def _open_source(self, source: Path) -> None:
        if source == self._source_path:
            return
        self._close_session()
        try:
            image_path = (self._pipeline_request.image_path
                          if self._pipeline_request is not None
                          and source == self._pipeline_request.tracking_path
                          else None)
            self._tracking_session = TrackingViewerSession(
                source, image_path=image_path)
        except Exception as error:
            self.status_label.setText(str(error))
            return
        session = self._tracking_session
        self._source_path = source
        self._image_session = session.image_session
        self.channel_combo.clear()
        self.channel_combo.addItems(session.channel_labels)
        self.mask_channel_combo.clear()
        self.mask_channel_combo.addItems(session.track_channel_labels)
        self.frame_slider.setRange(0, session.frame_count - 1)
        self.z_slider.setRange(0, session.plane_count - 1)
        self._set_source_controls_enabled(True)
        has_raw_image = session.image_session is not None
        self.raw_image_toggle.setEnabled(has_raw_image)
        self.raw_image_toggle.setChecked(has_raw_image)
        self.channel_combo.setEnabled(has_raw_image)
        self.grayscale_lut_button.setEnabled(has_raw_image)
        self.mask_channel_combo.setEnabled(True)
        if not self.editing_enabled:
            self.save_display_button.setEnabled(True)
        if self._pipeline_request is not None:
            self.save_tracking_button.setEnabled(True)
        self.local_cell_diameter.setEnabled(True)
        self._display_selection()
        self.diameter_reference.refresh()
        self._update_edit_buttons()
        image_note = "with raw image" if has_raw_image else "without raw image"
        mode_note = "new empty tracking session" if session.started_from_image else image_note
        self.status_label.setText(
            f"Loaded {source.parent.name} — axes {session.axes}, shape {session.shape}, "
            f"{mode_note}.")

    def _display_overlay(self, image, frame, channel, z_index) -> None:
        del image, channel
        self.diameter_reference.refresh()
        if self._tracking_session is not None and self.mask_channel_combo.currentIndex() >= 0:
            if self._split_preview is not None and self._preview_matches_current_view():
                self.image_viewer.set_mask_color(None)
                self.image_viewer.set_mask(
                    self._tracking_session.split_preview_labels(self._split_preview))
                return
            if self.preview_split_button.isChecked():
                labels = self._tracking_session.filtered_tracked_frame(
                    frame, self.mask_channel_combo.currentText(), z_index,
                    self._accepted_track_ids()).copy()
                if self._selected_track_ids:
                    labels[labels == self._selected_track_ids[0]] = 0
                self.image_viewer.set_mask_color(self._other_mask_color)
                self.image_viewer.set_mask(labels)
                return
            if self._collect_local_prompts and self._local_context_matches_current_view():
                labels = self._tracking_session.filtered_tracked_frame(
                    frame, self.mask_channel_combo.currentText(), z_index,
                    self._accepted_track_ids()).copy()
                if self._local_target_track_id is not None:
                    labels[labels == self._local_target_track_id] = 0
                self.image_viewer.set_mask_color(self._other_mask_color)
                self.image_viewer.set_mask(labels)
                return
            self.image_viewer.set_mask_color(None)
            self.image_viewer.set_mask(
                self._tracking_session.filtered_tracked_frame(
                    frame, self.mask_channel_combo.currentText(), z_index,
                    self._accepted_track_ids()))

    def _accepted_track_ids(self) -> frozenset[int] | None:
        session = self._tracking_session
        if (session is None or not self.filter_tracks.isChecked()
                or self.mask_channel_combo.currentIndex() < 0):
            return None
        return session.track_ids_matching(
            self.mask_channel_combo.currentText(), self.z_slider.value(),
            str(self.filter_operator.currentData()), self.filter_value.value(),
            self.filter_maximum.value())

    @Slot()
    def _filter_changed(self) -> None:
        between = self.filter_operator.currentData() == "between"
        self.filter_maximum.setVisible(between)
        enabled = self.filter_tracks.isChecked()
        self.filter_operator.setEnabled(enabled)
        self.filter_value.setEnabled(enabled)
        self.filter_maximum.setEnabled(enabled)
        self._display_selection()

    @Slot()
    def _display_selection(self) -> None:
        if (self._collect_local_prompts or self._local_segmentation_preview is not None):
            if not self._local_context_matches_current_view():
                self._clear_local_segmentation_state()
        if self._split_preview is not None and not self._preview_matches_current_view():
            self._split_preview = None
            self._update_edit_buttons()
        super()._display_selection()
        self.image_viewer.image_item.setVisible(self.raw_image_toggle.isChecked())
        self._display_track_paths()

    @Slot()
    def _display_track_paths(self) -> None:
        self._clear_track_paths()
        session = self._tracking_session
        if (session is None or not self.show_track_paths.isChecked()
                or self.mask_channel_combo.currentIndex() < 0):
            return
        centroids = session.track_centroids(
            self.mask_channel_combo.currentText(), self.z_slider.value())
        accepted = self._accepted_track_ids()
        if accepted is not None:
            centroids = {track_id: points for track_id, points in centroids.items()
                         if track_id in accepted}
        current_frame = self.frame_slider.value()
        full_path = self.path_extent.currentData() == "full"
        thickness = self.path_thickness.value()
        show_markers = self.show_centroids.isChecked()
        visible_tracks = {}
        for track_id, points in centroids.items():
            visible = points if full_path else points[points[:, 0] <= current_frame]
            if not len(visible):
                continue
            visible_tracks[track_id] = visible
        item = TrackPathsItem()
        item.set_tracks(visible_tracks, color_for=self._track_color,
                        thickness=thickness, show_markers=show_markers,
                        marker_size=self.centroid_size.value())
        item.setZValue(50)
        self.image_viewer.view_box.addItem(item)
        self._track_path_items.append(item)

    def _track_color(self, track_id: int) -> QColor:
        if track_id in self._selected_track_ids:
            return QColor(255, 255, 255)
        if self.path_color_mode.currentData() == "single":
            return self._path_color
        hue = (track_id * 0.61803398875) % 1.0
        red, green, blue = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
        return QColor.fromRgbF(red, green, blue)

    @Slot(object)
    def _tracking_scene_clicked(self, event: object) -> None:
        if (not self.editing_enabled
                or self._tracking_session is None
                or self._save_thread is not None
                or not hasattr(event, "button")):
            return
        scene_position = event.scenePos()
        if not self.image_viewer.view_box.sceneBoundingRect().contains(scene_position):
            return
        position = self.image_viewer.view_box.mapSceneToView(scene_position)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        control = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if not control:
            return
        track_id = self._track_at_position(position.x(), position.y())
        if track_id is not None:
            if self._collect_local_prompts:
                self._switch_local_edit_target(track_id)
                return
            if self.preview_split_button.isChecked():
                self._switch_split_target(track_id)
                return
            self._toggle_track_selection(track_id)

    def _switch_local_edit_target(self, track_id: int) -> None:
        active = (self._local_target_track_id == track_id
                  and self._selected_track_ids == [track_id])
        self._clear_local_segmentation_state(stop_mode=False)
        self._selected_track_ids[:] = [] if active else [track_id]
        self._start_local_segmentation()
        action = "unselected" if active else "selected for editing"
        self.status_label.setText(
            f"Track {track_id} {action}. Press S to accept the current mask.")

    def _track_at_position(self, x_position: float, y_position: float) -> int | None:
        session = self._tracking_session
        if session is None:
            return None
        frame = self.frame_slider.value()
        channel = self.mask_channel_combo.currentText()
        z_index = self.z_slider.value()
        labels = session.tracked_frame(frame, channel, z_index)
        row, column = int(round(y_position)), int(round(x_position))
        if 0 <= row < labels.shape[0] and 0 <= column < labels.shape[1]:
            label = int(labels[row, column])
            if label:
                return label
        if not self.show_track_paths.isChecked():
            return None
        centroids = session.track_centroids(channel, z_index)
        accepted = self._accepted_track_ids()
        x_pixel, y_pixel = self.image_viewer.view_box.viewPixelSize()
        click = np.asarray([x_position / x_pixel, y_position / y_pixel])
        closest: tuple[float, int] | None = None
        for track_id, points in centroids.items():
            if accepted is not None and track_id not in accepted:
                continue
            visible = (points if self.path_extent.currentData() == "full" else
                       points[points[:, 0] <= frame])
            if not len(visible):
                continue
            path = visible[:, 1:3] / np.asarray([x_pixel, y_pixel])
            distance = self._distance_to_polyline(click, path)
            if distance <= 8 and (closest is None or distance < closest[0]):
                closest = distance, track_id
        return None if closest is None else closest[1]

    @staticmethod
    def _distance_to_polyline(point: np.ndarray, path: np.ndarray) -> float:
        if len(path) == 1:
            return float(np.linalg.norm(point - path[0]))
        starts = path[:-1]
        vectors = path[1:] - starts
        lengths = np.sum(vectors * vectors, axis=1)
        fractions = np.divide(
            np.sum((point - starts) * vectors, axis=1), lengths,
            out=np.zeros_like(lengths), where=lengths != 0)
        fractions = np.clip(fractions, 0.0, 1.0)
        projected = starts + fractions[:, None] * vectors
        return float(np.min(np.linalg.norm(projected - point, axis=1)))

    def _toggle_track_selection(self, track_id: int) -> None:
        if self._save_thread is not None:
            return
        self._split_preview = None
        if track_id in self._selected_track_ids:
            self._selected_track_ids.remove(track_id)
        elif len(self._selected_track_ids) < 2:
            self._selected_track_ids.append(track_id)
        else:
            self.status_label.setText(
                "Two tracks are already selected; clear one before selecting another.")
            return
        self._update_edit_buttons()
        self._display_track_paths()

    @Slot()
    def _clear_track_selection(self) -> None:
        self._split_preview = None
        self._selected_track_ids.clear()
        self._update_edit_buttons()
        self._display_track_paths()

    def _update_edit_buttons(self) -> None:
        count = len(self._selected_track_ids)
        local_busy = self._local_segmentation_thread is not None
        local_active = self._collect_local_prompts or self._local_segmentation_preview is not None
        editable = (self._save_thread is None
                    and self._tracking_save_thread is None
                    and self._split_preview is None
                    and not local_active and not local_busy)
        selected = ", ".join(map(str, self._selected_track_ids)) or "none"
        self.track_selection_label.setText(f"Selected tracks: {selected}")
        self.merge_tracks_button.setEnabled(editable and count == 2)
        self.link_tracks_button.setEnabled(editable and count == 2)
        self.stop_track_button.setEnabled(editable and count == 1)
        self.clear_track_selection_button.setEnabled(editable and count > 0)
        split_mode_available = (self._tracking_session is not None
                                and self._tracking_save_thread is None
                                and not local_active and not local_busy)
        self.preview_split_button.setEnabled(split_mode_available)
        self.apply_split_button.setEnabled(self._split_preview is not None)
        self.cancel_split_button.setEnabled(self._split_preview is not None)
        has_image = (self._tracking_session is not None
                     and self._tracking_session.image_session is not None)
        self.delete_mask_button.setEnabled(editable and count == 1)
        self.add_mask_button.setEnabled(
            has_image and self._save_thread is None
            and self._tracking_save_thread is None
            and (local_active or count <= 1))
        self.accept_mask_button.setEnabled(
            self._local_segmentation_preview is not None and not local_busy)
        self.cancel_mask_button.setEnabled(local_active and not local_busy)
        split_drawing = (self.preview_split_button.isChecked()
                         and count == 1 and self._split_preview is None)
        self.local_brush_size.setEnabled(
            (local_active or split_drawing) and not local_busy)

    @Slot(bool)
    def _toggle_split_mode(self, enabled: bool) -> None:
        if enabled:
            if self.add_mask_button.isChecked():
                self.add_mask_button.setChecked(False)
            if len(self._selected_track_ids) == 1:
                self._start_split_guidance()
            else:
                self._display_selection()
                self.status_label.setText(
                    "Split mode: Ctrl+click a mask or centroid to select it.")
            return
        if self._split_preview is not None:
            self._split_preview = None
        self.image_viewer.set_drawing_enabled(False)
        self.image_viewer.clear_drawing_overlay()
        self.image_viewer.set_mask_color(None)
        self._display_selection()
        self._update_edit_buttons()
        self.status_label.setText("Split mode stopped.")

    def _switch_split_target(self, track_id: int) -> None:
        active = self._selected_track_ids == [track_id]
        self._split_preview = None
        self._selected_track_ids[:] = [] if active else [track_id]
        if active:
            self.image_viewer.set_drawing_enabled(False)
            self.image_viewer.clear_drawing_overlay()
            self._display_selection()
            self.status_label.setText(
                f"Track {track_id} unselected. Ctrl+click another mask to split.")
            return
        self._start_split_guidance()

    def _start_split_guidance(self) -> None:
        if self._tracking_session is None or len(self._selected_track_ids) != 1:
            return
        track_id = self._selected_track_ids[0]
        selected = self._tracking_session.tracked_frame(
            self.frame_slider.value(), self.mask_channel_combo.currentText(),
            self.z_slider.value()) == track_id
        if not np.any(selected):
            self.status_label.setText("The selected track has no mask in this frame.")
            return
        self._split_preview = None
        self._display_selection()
        self.image_viewer.set_drawing_style(self._active_mask_color, 0.65)
        self.image_viewer.set_drawing_mask(selected.astype(np.uint8))
        self.image_viewer.set_drawing_options(
            "edit", "brush", "add", self.local_brush_size.value())
        self.image_viewer.set_drawing_enabled(True)
        self._update_edit_buttons()
        self.status_label.setText(
            "Click where the division should pass, or drag along the proposed split line.")

    def _local_context_matches_current_view(self) -> bool:
        preview = self._local_segmentation_preview
        if preview is not None:
            return self._local_preview_matches_current_view()
        session = self._tracking_session
        return bool(
            self._local_segmentation_context is not None and session is not None
            and self._local_segmentation_context == (
                self.frame_slider.value(),
                session._resolve_channel(self.mask_channel_combo.currentText()),
                self.z_slider.value()))

    def _local_preview_matches_current_view(self) -> bool:
        preview = self._local_segmentation_preview
        session = self._tracking_session
        return bool(
            preview is not None and session is not None
            and preview["frame_index"] == self.frame_slider.value()
            and preview["mask_channel"] == session._resolve_channel(
                self.mask_channel_combo.currentText())
            and preview["z_index"] == self.z_slider.value())

    @Slot()
    def _delete_selected_mask(self) -> None:
        if len(self._selected_track_ids) != 1:
            return
        session, channel, z_index = self._edit_context()
        track_id = self._selected_track_ids[0]
        try:
            session.delete_mask(track_id, self.frame_slider.value(), channel, z_index)
        except ValueError as error:
            QMessageBox.warning(self, "Cannot delete mask", str(error))
            return
        self._finish_track_edit(
            f"Deleted track {track_id}'s mask from frame {self.frame_slider.value() + 1}.")

    @Slot(bool)
    def _toggle_local_segmentation_mode(self, enabled: bool) -> None:
        if enabled:
            if self.preview_split_button.isChecked():
                self.preview_split_button.setChecked(False)
            self._start_local_segmentation()
            return
        if self._collect_local_prompts or self._local_segmentation_preview is not None:
            self._clear_local_segmentation_state(stop_mode=False)
            self._update_edit_buttons()
            self._display_selection()
            self.status_label.setText("Add masks mode stopped.")

    def _start_local_segmentation(self) -> None:
        if len(self._selected_track_ids) > 1 or self._tracking_session is None:
            self.add_mask_button.setChecked(False)
            return
        self._local_target_is_new = not self._selected_track_ids
        track_id = (self._tracking_session.next_track_id()
                    if self._local_target_is_new else self._selected_track_ids[0])
        self._local_target_track_id = track_id
        labels = self._tracking_session.tracked_frame(
            self.frame_slider.value(), self.mask_channel_combo.currentText(),
            self.z_slider.value())
        existing_mask = labels == track_id
        self._positive_points.clear()
        self._negative_points.clear()
        self._local_segmentation_preview = None
        self._collect_local_prompts = True
        self._local_segmentation_context = (
            self.frame_slider.value(),
            self._tracking_session._resolve_channel(self.mask_channel_combo.currentText()),
            self.z_slider.value())
        self._configure_local_drawing()
        image = self._tracking_session.display_frame(
            self.frame_slider.value(), self.channel_combo.currentText(),
            self.z_slider.value())
        if np.any(existing_mask):
            self._local_segmentation_preview = {
                "track_id": track_id,
                "frame_index": self.frame_slider.value(),
                "mask_channel": self._tracking_session._resolve_channel(
                    self.mask_channel_combo.currentText()),
                "image_channel": self.channel_combo.currentText(),
                "z_index": self.z_slider.value(),
                "bounds": (0, image.shape[0], 0, image.shape[1]),
                "mask": existing_mask.copy(),
                "replace_existing": True,
                "auxiliary_weight": 0.0,
                "temporal_weight": 0.0,
            }
        self._manual_excluded_mask = np.zeros(image.shape, dtype=bool)
        self._update_edit_buttons()
        self._display_selection()
        self.image_viewer.set_drawing_style(self._active_mask_color, 0.65)
        self.image_viewer.set_drawing_mask(existing_mask.astype(np.uint8))
        self.image_viewer.set_drawing_enabled(True)
        action = ("Edit the highlighted mask" if np.any(existing_mask)
                  else "Click inside the missing cell")
        self.status_label.setText(
            f"{action}. Right-click regions that should be excluded; press S to accept.")

    @Slot()
    def _configure_local_drawing(self) -> None:
        self.image_viewer.set_drawing_options(
            "edit", "brush", "add", self.local_brush_size.value())

    @Slot(object)
    def _local_drawing_finished(self, drawing: object) -> None:
        if self.preview_split_button.isChecked():
            selection = self.image_viewer.last_drawing_selection
            if selection is not None and np.any(selection):
                self._preview_selected_split(guide=selection)
            return
        session = self._tracking_session
        if (not self._collect_local_prompts or session is None
                or self._local_segmentation_thread is not None):
            return
        selection = self.image_viewer.last_drawing_selection
        if selection is None or not np.any(selection):
            return
        operation = self.image_viewer.last_drawing_operation
        if self._manual_excluded_mask is None:
            self._manual_excluded_mask = np.zeros(selection.shape, dtype=bool)
        if operation == "erase":
            self._manual_excluded_mask |= selection
        else:
            self._manual_excluded_mask[selection] = False
        if self.image_viewer.last_drawing_was_click:
            coordinates = np.column_stack(np.nonzero(selection))
            point_y, point_x = np.round(np.mean(coordinates, axis=0)).astype(int)
            self._add_local_segmentation_prompt(
                int(point_y), int(point_x), positive=operation == "add")
            return
        mask = np.asarray(drawing, dtype=bool)
        mask = self._clip_local_mask(mask)
        self.image_viewer.set_drawing_mask(mask.astype(np.uint8))
        if not np.any(mask):
            self._local_segmentation_preview = None
            self._manual_excluded_mask = np.zeros(mask.shape, dtype=bool)
            self._update_edit_buttons()
            self.status_label.setText(
                "The working mask is empty. Draw or click to predict a new mask.")
            return
        self._local_segmentation_preview = {
            "track_id": self._local_target_track_id,
            "frame_index": self.frame_slider.value(),
            "mask_channel": session._resolve_channel(
                self.mask_channel_combo.currentText()),
            "image_channel": self.channel_combo.currentText(),
            "z_index": self.z_slider.value(),
            "bounds": (0, mask.shape[0], 0, mask.shape[1]),
            "mask": mask,
            "auxiliary_weight": 0.0,
            "temporal_weight": 0.0,
            "replace_existing": not self._local_target_is_new,
        }
        if operation == "add" and not self._positive_points:
            coordinates = np.column_stack(np.nonzero(mask))
            center = np.mean(coordinates, axis=0)
            nearest = coordinates[np.argmin(np.sum((coordinates - center) ** 2, axis=1))]
            self._positive_points.append((int(nearest[0]), int(nearest[1])))
        self._update_edit_buttons()
        self.status_label.setText(
            "Manual mask updated. Continue drawing, accept it, or cancel this frame.")

    def _add_local_segmentation_prompt(self, y: int, x: int, *, positive: bool) -> None:
        session = self._tracking_session
        if session is None or self._local_segmentation_thread is not None:
            return
        image = session.display_frame(
            self.frame_slider.value(), self.channel_combo.currentText(), self.z_slider.value())
        if y < 0 or x < 0 or y >= image.shape[0] or x >= image.shape[1]:
            return
        labels = session.tracked_frame(
            self.frame_slider.value(), self.mask_channel_combo.currentText(),
            self.z_slider.value())
        occupied = int(labels[y, x])
        if positive and occupied not in (0, self._local_target_track_id):
            self.status_label.setText(
                f"Track {occupied} occupies this pixel. Ctrl+click it to edit that mask.")
            return
        if positive:
            self._positive_points.append((y, x))
        else:
            if not self._positive_points:
                self.status_label.setText("Place a foreground point before adding background points.")
                return
            self._negative_points.append((y, x))
        if not self._positive_points:
            return
        options = dict(
            track_id=self._local_target_track_id,
            frame_index=self.frame_slider.value(),
            image_channel=self.channel_combo.currentText(),
            mask_channel=self.mask_channel_combo.currentText(),
            z_index=self.z_slider.value(),
            positive_points=list(self._positive_points),
            negative_points=list(self._negative_points),
            expected_diameter=self.local_cell_diameter.value(),
            initial_mask=self.image_viewer.drawing_mask,
            excluded_mask=(None if self._manual_excluded_mask is None else
                           self._manual_excluded_mask.copy()),
        )
        thread = QThread(self)
        worker = _LocalSegmentationWorker(session, options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._local_segmentation_ready)
        worker.failed.connect(self._local_segmentation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._local_segmentation_finished)
        self._local_segmentation_thread = thread
        self._local_segmentation_worker = worker
        self.progress.show()
        self.image_viewer.set_drawing_enabled(False)
        self.image_viewer.clear_drawing_overlay()
        self.status_label.setText("Predicting local mask…")
        self._update_edit_buttons()
        thread.start()

    @Slot(object)
    def _local_segmentation_ready(self, preview: object) -> None:
        if isinstance(preview, dict):
            session = self._tracking_session
            if (session is None or self._local_target_track_id is None
                    or int(preview["track_id"]) != self._local_target_track_id
                    or preview["frame_index"] != self.frame_slider.value()
                    or preview["mask_channel"] != session._resolve_channel(
                        self.mask_channel_combo.currentText())
                    or preview["z_index"] != self.z_slider.value()):
                return
            preview = dict(preview)
            y0, y1, x0, x1 = preview["bounds"]
            full_mask = np.zeros(session.tracked_frame(
                int(preview["frame_index"]), int(preview["mask_channel"]),
                int(preview["z_index"])).shape, dtype=bool)
            full_mask[y0:y1, x0:x1] = np.asarray(preview["mask"], dtype=bool)
            clipped = self._clip_local_mask(full_mask)
            preview["bounds"] = (0, clipped.shape[0], 0, clipped.shape[1])
            preview["mask"] = clipped
            self._local_segmentation_preview = preview
            self._display_selection()
            self._set_local_drawing_from_preview(preview)
            weight = float(preview.get("auxiliary_weight", 0.0))
            note = f" Cross-channel support: {weight:.0%}." if weight > 0 else ""
            temporal_weight = float(preview.get("temporal_weight", 0.0))
            if temporal_weight > 0:
                note += f" Previous-frame support: {temporal_weight:.0%}."
            self.status_label.setText(
                "Mask preview updated. Add clicks, accept, or cancel." + note)

    def _clip_local_mask(self, mask: np.ndarray) -> np.ndarray:
        session = self._tracking_session
        if session is None:
            return np.asarray(mask, dtype=bool)
        labels = session.tracked_frame(
            self.frame_slider.value(), self.mask_channel_combo.currentText(),
            self.z_slider.value())
        allowed = labels == 0
        if self._local_target_track_id is not None:
            allowed |= labels == self._local_target_track_id
        return np.asarray(mask, dtype=bool) & allowed

    @Slot(str)
    def _local_segmentation_failed(self, message: str) -> None:
        self.image_viewer.set_drawing_enabled(True)
        self.status_label.setText(message)

    @Slot()
    def _local_segmentation_finished(self) -> None:
        thread = self._local_segmentation_thread
        self._local_segmentation_worker = None
        self._local_segmentation_thread = None
        self.progress.hide()
        self._update_edit_buttons()
        if thread is not None:
            thread.deleteLater()

    def _set_local_drawing_from_preview(self, preview: dict[str, object]) -> None:
        session = self._tracking_session
        if session is None:
            return
        shape = session.tracked_frame(
            int(preview["frame_index"]), int(preview["mask_channel"]),
            int(preview["z_index"])).shape
        drawing = np.zeros(shape, dtype=np.uint8)
        y0, y1, x0, x1 = preview["bounds"]
        drawing[y0:y1, x0:x1] = np.asarray(preview["mask"], dtype=np.uint8)
        self.image_viewer.set_drawing_mask(drawing)
        self.image_viewer.set_drawing_enabled(True)

    @Slot()
    def _accept_local_segmentation(self) -> None:
        if self._local_segmentation_preview is None or self._tracking_session is None:
            return
        track_id = int(self._local_segmentation_preview["track_id"])
        try:
            self._tracking_session.apply_add_edit(
                self._local_segmentation_preview)
        except ValueError as error:
            QMessageBox.warning(self, "Cannot add mask", str(error))
            return
        completed_frame = self.frame_slider.value()
        self._selected_track_ids[:] = [track_id]
        if completed_frame >= self.frame_slider.maximum():
            self._clear_local_segmentation_state()
            self._update_edit_buttons()
            self._display_selection()
            self.status_label.setText(
                f"Added a mask to track {track_id} in the last frame; add masks mode stopped.")
            return
        self._clear_local_segmentation_state(stop_mode=False)
        self.frame_slider.setValue(completed_frame + 1)
        self._start_local_segmentation()
        self._display_track_paths()
        self.status_label.setText(
            f"Added a mask to track {track_id}; moved to frame {completed_frame + 2}. "
            "Click or draw the next mask, or turn off Add masks mode.")

    @Slot()
    def _cancel_local_segmentation(self) -> None:
        if not self._collect_local_prompts:
            return
        self._positive_points.clear()
        self._negative_points.clear()
        self._local_segmentation_preview = None
        session = self._tracking_session
        if session is not None:
            image = session.display_frame(
                self.frame_slider.value(), self.channel_combo.currentText(),
                self.z_slider.value())
            self.image_viewer.set_drawing_mask(np.zeros(image.shape, dtype=np.uint8))
            self._manual_excluded_mask = np.zeros(image.shape, dtype=bool)
        self._update_edit_buttons()
        self._display_selection()
        self.image_viewer.set_drawing_mask(np.zeros(
            self.image_viewer.image_item.image.shape, dtype=np.uint8))
        self.image_viewer.set_drawing_enabled(True)
        self.status_label.setText(
            "Current mask cleared. Click or draw again, or turn off Add masks mode.")

    def _clear_local_segmentation_state(self, *, stop_mode: bool = True) -> None:
        self._local_segmentation_preview = None
        self._positive_points.clear()
        self._negative_points.clear()
        self._collect_local_prompts = False
        self._local_segmentation_context = None
        self._local_target_track_id = None
        self._local_target_is_new = False
        self._manual_excluded_mask = None
        self.image_viewer.set_drawing_enabled(False)
        self.image_viewer.clear_drawing_overlay()
        self.image_viewer.set_mask_color(None)
        if stop_mode and self.add_mask_button.isChecked():
            self.add_mask_button.blockSignals(True)
            self.add_mask_button.setChecked(False)
            self.add_mask_button.blockSignals(False)

    def _choose_mask_edit_colors(self) -> None:
        dialog = _MaskColorDialog(
            self._active_mask_color, self._other_mask_color, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._active_mask_color = dialog.active_color
        self._other_mask_color = dialog.other_color
        self._apply_mask_edit_colors()

    def _apply_mask_edit_colors(self) -> None:
        self._update_mask_edit_colors_button()
        drawing = (self.image_viewer.drawing_mask
                   if self._collect_local_prompts else None)
        self.image_viewer.set_drawing_style(self._active_mask_color, 0.65)
        self._display_selection()
        if drawing is not None:
            self.image_viewer.set_drawing_mask(drawing)
            self.image_viewer.set_drawing_enabled(True)

    def _update_mask_edit_colors_button(self) -> None:
        self.mask_edit_colors_button.setStyleSheet(
            f"background-color: {self._active_mask_color.name()}; "
            f"border: 5px solid {self._other_mask_color.name()}; "
            "color: black; padding: 2px 6px;")

    def _preview_matches_current_view(self) -> bool:
        preview = self._split_preview
        session = self._tracking_session
        return bool(
            preview is not None and session is not None
            and preview["frame_index"] == self.frame_slider.value()
            and preview["channel"] == session._resolve_channel(
                self.mask_channel_combo.currentText())
            and preview["z_index"] == self.z_slider.value())

    @Slot()
    def _preview_selected_split(self, *, guide: np.ndarray | None = None) -> None:
        if len(self._selected_track_ids) != 1:
            return
        session, channel, z_index = self._edit_context()
        try:
            self._split_preview = session.preview_split(
                self._selected_track_ids[0], self.frame_slider.value(),
                channel, z_index,
                image_channel=self.channel_combo.currentText(), guide=guide)
        except ValueError as error:
            QMessageBox.warning(self, "Cannot split track", str(error))
            return
        method = str(self._split_preview["method"]).replace("_", " ")
        self.image_viewer.set_drawing_enabled(False)
        self.image_viewer.clear_drawing_overlay()
        self._update_edit_buttons()
        self._display_selection()
        self.status_label.setText(
            f"Split preview uses {method}. Press S or choose Accept split.")

    @Slot()
    def _apply_previewed_split(self) -> None:
        if self._split_preview is None or self._tracking_session is None:
            return
        track_id = int(self._split_preview["track_id"])
        try:
            new_track_id = self._tracking_session.apply_split(self._split_preview)
        except ValueError as error:
            QMessageBox.warning(self, "Cannot split track", str(error))
            return
        self._split_preview = None
        self._finish_track_edit(
            f"Split track {track_id}; the second region is track {new_track_id}.")
        if self.preview_split_button.isChecked():
            self._selected_track_ids[:] = [track_id]
            self._start_split_guidance()

    @Slot()
    def _cancel_split_preview(self) -> None:
        if self._split_preview is None:
            return
        self._split_preview = None
        self._update_edit_buttons()
        if self.preview_split_button.isChecked() and self._selected_track_ids:
            self._start_split_guidance()
        else:
            self._display_selection()
        self.status_label.setText("Split preview cancelled; draw or click again.")

    def _edit_context(self) -> tuple[TrackingViewerSession, str, int]:
        if self._tracking_session is None:
            raise RuntimeError("No tracking artifact is open.")
        return (self._tracking_session, self.mask_channel_combo.currentText(),
                self.z_slider.value())

    @Slot()
    def _merge_selected_tracks(self) -> None:
        if len(self._selected_track_ids) != 2:
            return
        session, channel, z_index = self._edit_context()
        selected = tuple(self._selected_track_ids)
        try:
            survivor = session.merge_tracks(
                selected, self.frame_slider.value(), channel, z_index)
        except ValueError as error:
            QMessageBox.warning(self, "Cannot merge tracks", str(error))
            return
        self._finish_track_edit(
            f"Merged tracks {selected[0]} and {selected[1]} into {survivor} "
            f"from frame {self.frame_slider.value() + 1}.")

    @Slot()
    def _link_selected_tracks(self) -> None:
        if len(self._selected_track_ids) != 2:
            return
        session, channel, z_index = self._edit_context()
        selected = tuple(self._selected_track_ids)
        try:
            target, conflict = session.link_tracks(selected, channel, z_index)
        except ValueError as error:
            QMessageBox.warning(self, "Cannot link tracks", str(error))
            return
        note = " using a new ID because their frames overlap" if conflict else ""
        self._finish_track_edit(
            f"Linked tracks {selected[0]} and {selected[1]} as {target}{note}.")

    @Slot()
    def _stop_selected_track(self) -> None:
        if len(self._selected_track_ids) != 1:
            return
        session, channel, z_index = self._edit_context()
        track_id = self._selected_track_ids[0]
        try:
            new_track_id = session.stop_track(
                track_id, self.frame_slider.value(), channel, z_index)
        except ValueError as error:
            QMessageBox.warning(self, "Cannot stop track", str(error))
            return
        self._finish_track_edit(
            f"Stopped track {track_id} after frame {self.frame_slider.value() + 1}; "
            f"later masks are track {new_track_id}.")

    def _finish_track_edit(self, message: str, preserve_track_id: int | None = None) -> None:
        self._split_preview = None
        self._selected_track_ids.clear()
        if preserve_track_id is not None:
            self._selected_track_ids.append(preserve_track_id)
        self._split_preview = None
        self._update_edit_buttons()
        self._display_selection()
        self.status_label.setText(message + " Edits are not saved to the tracking mask yet.")

    def _clear_track_paths(self) -> None:
        for item in self._track_path_items:
            self.image_viewer.view_box.removeItem(item)
        self._track_path_items.clear()

    def _path_color_mode_changed(self) -> None:
        single_color = self.path_color_mode.currentData() == "single"
        self.path_color_button.setVisible(single_color)
        self.path_color_button.setEnabled(single_color)
        self._display_track_paths()

    def _choose_path_color(self) -> None:
        color = QColorDialog.getColor(self._path_color, self, "Choose path color")
        if color.isValid():
            self._path_color = color
            self._update_path_color_button()
            self._display_track_paths()

    def _update_path_color_button(self) -> None:
        self.path_color_button.setStyleSheet(
            f"background-color: {self._path_color.name()}; color: black;")

    @Slot()
    def _save_current_display(self) -> None:
        session = self._tracking_session
        if session is None or self.mask_channel_combo.currentIndex() < 0:
            return
        label = self.display_label_edit.text().strip()
        filtered = self.filter_tracks.isChecked()
        name_parts = ["fits_track"]
        if filtered:
            name_parts.append("filtered")
        name_parts.append(label or "path")
        output_name = "_".join(name_parts) + ".tif"
        output_path = session.source_path.with_name(output_name)
        if output_path.exists():
            answer = QMessageBox.question(
                self, "Replace tracking display?",
                f"{output_name} already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,)
            if answer != QMessageBox.StandardButton.Yes:
                return
        display_settings = {
            "label": label or None,
            "raw_image_visible": self.raw_image_toggle.isChecked(),
            "raw_image_channel": self.channel_combo.currentText(),
            "raw_image_grayscale": self.grayscale_lut_button.isChecked(),
            "mask_visible": self.show_mask.isChecked(),
            "mask_opacity": self.mask_opacity.value() / 100.0,
            "mask_channel": self.mask_channel_combo.currentText(),
            "z_index": self.z_slider.value(),
            "track_paths_visible": self.show_track_paths.isChecked(),
            "path_extent": self.path_extent.currentData(),
            "path_thickness_px": self.path_thickness.value(),
            "path_color_mode": self.path_color_mode.currentData(),
            "path_color": self._path_color.name(),
            "centroid_markers_visible": self.show_centroids.isChecked(),
            "centroid_marker_size_px": self.centroid_size.value(),
            "filter": self._filter_metadata() if filtered else None,
            "output_mode": "rgb_rendering",
            "raw_image_exported": False,
        }
        options = dict(
                label=label,
                channel=self.mask_channel_combo.currentText(),
                z_index=self.z_slider.value(),
                show_paths=self.show_track_paths.isChecked(),
                path_extent=str(self.path_extent.currentData()),
                thickness=self.path_thickness.value(),
                show_centroids=self.show_centroids.isChecked(),
                marker_size=self.centroid_size.value(),
                path_color_mode=str(self.path_color_mode.currentData()),
                path_color=self._path_color.name(),
                mask_visible=self.show_mask.isChecked(),
                mask_opacity=self.mask_opacity.value() / 100.0,
                track_ids=self._accepted_track_ids(),
                filtered=filtered,
                display_metadata=display_settings,)
        self.save_display_button.setEnabled(False)
        self.progress.show()
        self.status_label.setText("Rendering and saving tracking display…")
        thread = QThread(self)
        worker = _SaveWorker(session, options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._display_saved)
        worker.failed.connect(self._display_save_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._save_thread_finished)
        self._save_thread = thread
        self._save_worker = worker
        self._update_edit_buttons()
        thread.start()

    def _filter_metadata(self) -> dict[str, object]:
        operator = str(self.filter_operator.currentData())
        symbols = {"lt": "<", "le": "<=", "eq": "==", "ne": "!=",
                   "ge": ">=", "gt": ">"}
        metadata: dict[str, object] = {
            "measurement": "track_length_frames",
        }
        if operator == "between":
            metadata["operator"] = "between"
            metadata["minimum"] = self.filter_value.value()
            metadata["maximum"] = self.filter_maximum.value()
            metadata["bounds_inclusive"] = True
            metadata["expression"] = (
                f"{self.filter_value.value()} <= track_length_frames <= "
                f"{self.filter_maximum.value()}")
        else:
            metadata["operator"] = symbols[operator]
            metadata["value"] = self.filter_value.value()
            metadata["expression"] = (
                f"track_length_frames {symbols[operator]} {self.filter_value.value()}")
        accepted = self._accepted_track_ids() or frozenset()
        metadata["retained_track_count"] = len(accepted)
        return metadata

    def _filter_spec(self) -> dict[str, object] | None:
        if not self.filter_tracks.isChecked():
            return None
        spec: dict[str, object] = {
            "operator": str(self.filter_operator.currentData()),
            "value": self.filter_value.value(),
        }
        if spec["operator"] == "between":
            spec["maximum"] = self.filter_maximum.value()
        return spec

    def _edited_filter_metadata(self) -> dict[str, object] | None:
        if not self.filter_tracks.isChecked():
            return None
        metadata = self._filter_metadata()
        metadata.pop("retained_track_count", None)
        metadata["scope"] = "each mask channel and Z plane"
        return metadata

    @Slot()
    def _save_edited_tracking(self) -> None:
        session = self._tracking_session
        request = self._pipeline_request
        if session is None or request is None or self._tracking_save_thread is not None:
            return
        filtered = self.filter_tracks.isChecked()
        output_name = (FITS_MASK_TRACK_EDITED_FILTERED if filtered
                       else FITS_MASK_TRACK_EDITED)
        output_path = session.source_path.with_name(output_name)
        if output_path.exists() and not request.overwrite:
            QMessageBox.warning(
                self, "Edited tracking already exists",
                f"{output_name} already exists. Enable overwrite for the Edit tracking "
                "step to replace it.")
            return
        options = {
            "filter_spec": self._filter_spec(),
            "filter_condition": self._edited_filter_metadata(),
            "pipeline_metadata": dict(request.pipeline_metadata or {}),
            "selected_mask_channel": self.mask_channel_combo.currentText(),
        }
        self.save_tracking_button.setEnabled(False)
        self.use_original_button.setEnabled(False)
        self.progress.show()
        self.status_label.setText("Saving edited tracking labels…")
        thread = QThread(self)
        worker = _TrackingSaveWorker(session, options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._edited_tracking_saved)
        worker.failed.connect(self._edited_tracking_save_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._tracking_save_finished)
        self._tracking_save_thread = thread
        self._tracking_save_worker = worker
        self._update_edit_buttons()
        thread.start()

    @Slot(object)
    def _edited_tracking_saved(self, result: object) -> None:
        request = self._pipeline_request
        if request is None or not isinstance(result, tuple) or len(result) != 2:
            return
        path, metadata = result
        self._pipeline_resolved = True
        self.tracking_finalized.emit(TrackEditOutcome(
            request=request,
            edited_path=Path(path),
            metadata=metadata,
        ))
        self.close()

    @Slot(str)
    def _edited_tracking_save_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Cannot save edited tracking", message)

    @Slot()
    def _tracking_save_finished(self) -> None:
        thread = self._tracking_save_thread
        self._tracking_save_worker = None
        self._tracking_save_thread = None
        self.progress.hide()
        if self._pipeline_request is not None and not self._pipeline_resolved:
            self.save_tracking_button.setEnabled(self._tracking_session is not None)
            self.use_original_button.setEnabled(True)
        self._update_edit_buttons()
        if thread is not None:
            thread.deleteLater()

    @Slot()
    def _use_original_tracking(self) -> None:
        request = self._pipeline_request
        if request is None or self._pipeline_resolved:
            return
        self._pipeline_resolved = True
        self.tracking_finalized.emit(TrackEditOutcome(
            request=request, edited_path=None, metadata=None))
        self.close()

    @Slot(object)
    def _display_saved(self, saved: object) -> None:
        self.status_label.setText(f"Saved tracking display to {Path(saved).name}.")

    @Slot(str)
    def _display_save_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Cannot save tracking display", message)

    @Slot()
    def _save_thread_finished(self) -> None:
        thread = self._save_thread
        self._save_worker = None
        self._save_thread = None
        self.progress.hide()
        self.save_display_button.setEnabled(self._tracking_session is not None)
        self._update_edit_buttons()
        if thread is not None:
            thread.deleteLater()

    def _clear_tools(self) -> None:
        self.diameter_reference.hide()
        self.local_cell_diameter.setEnabled(False)
        if (self._local_segmentation_thread is not None
                and self._local_segmentation_thread.isRunning()):
            self._local_segmentation_thread.quit()
            self._local_segmentation_thread.wait()
        self._clear_local_segmentation_state()
        if self._save_thread is not None and self._save_thread.isRunning():
            self._save_thread.quit()
            self._save_thread.wait()
        if (self._tracking_save_thread is not None
                and self._tracking_save_thread.isRunning()):
            self._tracking_save_thread.quit()
            self._tracking_save_thread.wait()
        self._clear_track_paths()
        self._selected_track_ids.clear()
        self._update_edit_buttons()
        self._tracking_session = None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._pipeline_request is not None and not self._pipeline_resolved:
            self._pipeline_resolved = True
            self.tracking_finalized.emit(TrackEditOutcome(
                request=self._pipeline_request, edited_path=None, metadata=None))
        super().closeEvent(event)
