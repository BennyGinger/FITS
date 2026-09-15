from __future__ import annotations

from pathlib import Path
import colorsys

import pyqtgraph as pg
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from fits.environment.constant import FITS_MASK_TRACK
from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.tracking.session import TrackingViewerSession


class TrackingViewerWindow(ImageToolWindow):
    """Initial tracked-label movie viewer; editing controls will follow."""

    file_filters = (FITS_MASK_TRACK,)
    tool_help = ""

    def __init__(self, experiments_dir: str | Path | None = None,
                 tracking_path: str | Path | None = None,
                 parent: QWidget | None = None) -> None:
        self._tracking_session: TrackingViewerSession | None = None
        self._track_path_items: list[pg.PlotDataItem] = []
        self._path_color = QColor(255, 215, 0)
        self.raw_image_toggle = QCheckBox("Display raw image")
        self.raw_image_toggle.setChecked(True)
        self.raw_image_toggle.setToolTip(
            "Show or hide the selected channel from the sibling fits_array.tif image.")
        super().__init__(experiments_dir, parent)
        self.setWindowTitle("FITS Tracking Viewer / Editor")
        self.left_display_controls.insertWidget(0, self.raw_image_toggle)
        self.left_display_controls.insertSpacing(1, 10)
        self.overlay_label.setText("Mask overlay")
        if tracking_path is not None:
            self._path_selected(Path(tracking_path))

    def _build_tools(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        display_section, display = self._section("Display settings")
        self.show_track_paths = QCheckBox("Show track paths")
        self.show_track_paths.setChecked(True)
        display.addWidget(self.show_track_paths)

        history_row = QHBoxLayout()
        history_row.addWidget(QLabel("Path extent"))
        self.path_extent = QComboBox()
        self.path_extent.addItem("Build to current frame", "built")
        self.path_extent.addItem("Show full path", "full")
        history_row.addWidget(self.path_extent, 1)
        display.addLayout(history_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Thickness"))
        self.path_thickness = QSpinBox()
        self.path_thickness.setRange(1, 12)
        self.path_thickness.setValue(2)
        self.path_thickness.setSuffix(" px")
        style_row.addWidget(self.path_thickness)
        style_row.addSpacing(16)
        style_row.addWidget(QLabel("Colors"))
        self.path_color_mode = QComboBox()
        self.path_color_mode.addItem("Match track palette", "track")
        self.path_color_mode.addItem("Single color", "single")
        style_row.addWidget(self.path_color_mode, 1)
        display.addLayout(style_row)

        detail_row = QHBoxLayout()
        self.path_color_button = QPushButton("Path color")
        self._update_path_color_button()
        self.path_color_button.setEnabled(False)
        detail_row.addWidget(self.path_color_button)
        self.show_centroids = QCheckBox("Show centroid markers")
        self.show_centroids.setChecked(True)
        detail_row.addWidget(self.show_centroids)
        detail_row.addStretch(1)
        display.addLayout(detail_row)
        layout.addWidget(display_section)
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
        self.raw_image_toggle.toggled.connect(self.image_viewer.image_item.setVisible)
        self.mask_channel_combo.currentIndexChanged.connect(self._display_selection)
        self.show_track_paths.toggled.connect(self._display_track_paths)
        self.path_extent.currentIndexChanged.connect(self._display_track_paths)
        self.path_thickness.valueChanged.connect(self._display_track_paths)
        self.path_color_mode.currentIndexChanged.connect(self._path_color_mode_changed)
        self.show_centroids.toggled.connect(self._display_track_paths)
        self.path_color_button.clicked.connect(self._choose_path_color)
        self.save_display_button.clicked.connect(self._save_current_display)

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        return False

    @Slot(object)
    def _path_selected(self, selected: object) -> None:
        if not isinstance(selected, (str, Path)):
            return
        source = Path(selected)
        if source.is_dir():
            source = source / FITS_MASK_TRACK
            if source.is_file() and self.directory_browser.select_path(source):
                return
        if source.name != FITS_MASK_TRACK or not source.is_file():
            self.status_label.setText(f"Select an experiment containing {FITS_MASK_TRACK}.")
            return
        self._open_source(source)

    def _open_source(self, source: Path) -> None:
        if source == self._source_path:
            return
        self._close_session()
        try:
            self._tracking_session = TrackingViewerSession(source)
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
        self.save_display_button.setEnabled(True)
        self._display_selection()
        image_note = "with raw image" if has_raw_image else "without raw image"
        self.status_label.setText(
            f"Loaded {source.parent.name} — axes {session.axes}, shape {session.shape}, "
            f"{image_note}.")

    def _display_overlay(self, image, frame, channel, z_index) -> None:
        del image, channel
        if self._tracking_session is not None and self.mask_channel_combo.currentIndex() >= 0:
            self.image_viewer.set_mask(
                self._tracking_session.tracked_frame(
                    frame, self.mask_channel_combo.currentText(), z_index))

    @Slot()
    def _display_selection(self) -> None:
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
        current_frame = self.frame_slider.value()
        full_path = self.path_extent.currentData() == "full"
        thickness = self.path_thickness.value()
        show_markers = self.show_centroids.isChecked()
        for track_id, points in centroids.items():
            visible = points if full_path else points[points[:, 0] <= current_frame]
            if not len(visible):
                continue
            color = self._track_color(track_id)
            item = pg.PlotDataItem(
                visible[:, 1], visible[:, 2],
                pen=pg.mkPen(color, width=thickness),
                symbol="o" if show_markers else None,
                symbolSize=max(4, thickness + 3),
                symbolPen=pg.mkPen(color),
                symbolBrush=pg.mkBrush(color),)
            item.setZValue(50)
            self.image_viewer.view_box.addItem(item)
            self._track_path_items.append(item)

    def _track_color(self, track_id: int) -> QColor:
        if self.path_color_mode.currentData() == "single":
            return self._path_color
        hue = (track_id * 0.61803398875) % 1.0
        red, green, blue = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
        return QColor.fromRgbF(red, green, blue)

    def _clear_track_paths(self) -> None:
        for item in self._track_path_items:
            self.image_viewer.view_box.removeItem(item)
        self._track_path_items.clear()

    def _path_color_mode_changed(self) -> None:
        self.path_color_button.setEnabled(
            self.path_color_mode.currentData() == "single")
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
        output_name = f"fits_track_{label or 'path'}.tif"
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
            "output_mode": "rgb_rendering",
            "raw_image_exported": False,
        }
        try:
            saved = session.save_rendered_display(
                label=label,
                channel=self.mask_channel_combo.currentText(),
                z_index=self.z_slider.value(),
                show_paths=self.show_track_paths.isChecked(),
                path_extent=str(self.path_extent.currentData()),
                thickness=self.path_thickness.value(),
                show_centroids=self.show_centroids.isChecked(),
                path_color_mode=str(self.path_color_mode.currentData()),
                path_color=self._path_color.name(),
                mask_visible=self.show_mask.isChecked(),
                mask_opacity=self.mask_opacity.value() / 100.0,
                display_metadata=display_settings,)
        except Exception as error:
            QMessageBox.warning(self, "Cannot save tracking display", str(error))
            return
        self.status_label.setText(f"Saved tracking display to {saved.name}.")

    def _clear_tools(self) -> None:
        self._clear_track_paths()
        self._tracking_session = None
