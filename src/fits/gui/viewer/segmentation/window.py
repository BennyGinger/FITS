from __future__ import annotations
from numpy.typing import NDArray
from collections.abc import Mapping
from pathlib import Path
from fits.environment import constant as cst
from typing import Any
import numpy as np
from PySide6.QtCore import QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent, QColor, QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QDoubleSpinBox, QCheckBox, QComboBox, QLineEdit, QTabWidget, QMessageBox, QSpinBox
from fits.workflows.artifacts.paths import image_input_for, image_for, first_image
from fits.environment.constant import IMAGE_NAMES, FITS_ARRAY_NAME
from fits.gui.settings import SettingsAdapter
from fits.gui.theme import STEP_TAB_BAR_STYLE
from fits.gui.viewer.common.base_window import ImageToolWindow
from fits.gui.viewer.common.information_dialog import SEGMENTATION_HELP
from fits.gui.viewer.segmentation.settings_panel import CellposeSettingsPanel
from fits.gui.viewer.segmentation.diameter_reference import DiameterReference
from fits.gui.viewer.segmentation.worker import ModelInitializationRequest, ModelInitializationWorker, PreviewOutcome, PreviewRequest, PreviewWorker
from fits.settings.models import SegmentSettings, SegmentChannelSettings, ExtractSettings
from fits.settings.loader import run_settings_path
from fits.tasks.segmentation.preview_cache import SegmentationPreview
from fits.tasks.segmentation.tuning import SegmentationTuningSession
from fits.gui.viewer.segmentation.compartment_panel import CompartmentPanel
from fits.gui.viewer.segmentation.mask_preview import MaskPreviewStore, saved_mask_path
from fits.gui.viewer.common.mask_colours import MaskColourControl


class SegmentationTunerWindow(ImageToolWindow):
    """
    Inspect segmentation/compartments and save each tab's validated settings.
    """

    settings_applied = Signal(object)
    compartment_settings_applied = Signal(object)
    channel_removed = Signal(str)
    auto_open_first_image = True
    file_filters = IMAGE_NAMES
    help_gui = "SegTune"
    tool_help = SEGMENTATION_HELP

    def __init__(self,
                 experiments_dir: str | Path | None = None,
                 segment_settings: SegmentSettings | Mapping[str, Any] | None = None,
                 parent: QWidget | None = None,
                 *,
                 initial_path: str | Path | None = None,
                 directory_locked: bool = False,
                 extract_settings: ExtractSettings | None = None,
                 initial_tab: str = "segmentation",
                 ) -> None:
        """
        Initialize the SegmentationTunerWindow state and dependencies.
        """
        self._provided_settings = (SegmentSettings.model_validate(segment_settings)
                                   if segment_settings is not None else None)
        self._extract_provided = extract_settings is not None
        self._extract_settings = extract_settings or ExtractSettings()
        self._mask_previews = MaskPreviewStore()
        self._saved_entries: list[SegmentChannelSettings] = []
        self._saved_baseline_set = False
        self._mask_colours = [(0, QColor("yellow")), (0, QColor("yellow"))]
        self._last_tab = 0
        self._requested_tab = initial_tab
        self._standalone = parent is None
        self._save_root = Path(experiments_dir) if experiments_dir is not None else None
        self._automatic_preview = False
        self._entries: list[SegmentChannelSettings] = []
        self._entry_index = 0
        self._loading_entry = False
        self._segmentation_session: SegmentationTuningSession | None = None
        self._thread: QThread | None = None
        self._worker: PreviewWorker | ModelInitializationWorker | None = None
        self._active_request: PreviewRequest | None = None
        self._active_operation: str | None = None
        self._pending_model_settings: SegmentChannelSettings | None = None
        super().__init__(None, parent, directory_locked=directory_locked)
        self._model_change_timer = QTimer(self)
        self._model_change_timer.setSingleShot(True)
        self._model_change_timer.setInterval(300)
        self._model_change_timer.timeout.connect(self._initialize_selected_model)
        self.settings_panel.model_settings_changed.connect(self._model_change_timer.start)
        for widget in self.settings_panel.findChildren(QDoubleSpinBox) + self.settings_panel.findChildren(QSpinBox):
            widget.valueChanged.connect(self._settings_edited)
        for widget in self.settings_panel.findChildren(QCheckBox):
            widget.toggled.connect(self._settings_edited)
        for widget in self.settings_panel.findChildren(QComboBox):
            widget.currentIndexChanged.connect(self._settings_edited)
        for widget in self.settings_panel.findChildren(QLineEdit):
            widget.textChanged.connect(self._settings_edited)
        self.channel_combo.currentIndexChanged.connect(self._settings_edited)
        self.setWindowTitle("FITS Segmentation and Compartment Tuner")
        self.resize(1500, 950)
        self._apply_tab_appearance()
        if initial_tab == "compartment":
            self.tool_tabs.setCurrentIndex(1)
        if experiments_dir is not None:
            self._set_experiments_directory(experiments_dir, initial_path=initial_path)

    def _build_tools(self) -> QWidget:
        """
        Build tools.
        """
        self.settings_panel = CellposeSettingsPanel()
        self.settings_panel.overlay_widget.hide()
        layout = self.settings_panel.layout()
        assert isinstance(layout, QVBoxLayout)
        controls = self.settings_panel.controls_scroll.widget()
        assert controls is not None
        controls_layout = controls.layout()
        assert isinstance(controls_layout, QVBoxLayout)
        controls_layout.removeWidget(self.settings_panel.run_button)
        layout.removeWidget(self.settings_panel.apply_button)

        self.channel_settings_list = QListWidget()
        self.channel_settings_list.setMinimumHeight(180)
        self.channel_settings_list.setMaximumHeight(300)
        self.channel_settings_list.currentRowChanged.connect(self._select_entry)
        header = QHBoxLayout()
        header.addWidget(QLabel("Channel settings"))
        self.channel_settings_header = header
        layout.addLayout(header)
        layout.addWidget(self.channel_settings_list, 1)
        layout.setStretchFactor(self.settings_panel.controls_scroll, 3)
        self.add_channel_button = QPushButton("Add channel")
        self.add_channel_button.setStyleSheet(
            "QPushButton { background-color: #4f8f5b; color: white; "
            "padding: 6px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #5ca568; } "
            "QPushButton:pressed { background-color: #3f7449; }")
        self.add_channel_button.setEnabled(False)
        self.add_channel_button.clicked.connect(self._add_channel)
        self.channel_settings_header.addWidget(self.add_channel_button)
        self.compartment_panel = CompartmentPanel(self._extract_settings)
        self.tool_tabs = QTabWidget()
        self.tool_tabs.setObjectName("stepSettingsTabs")
        self.tool_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #626262; } "
            "QTabBar::tab { padding: 7px 15px; } "
            "QTabBar::tab:selected { background: #526170; font-weight: bold; }")
        self.tool_tabs.tabBar().setStyleSheet(STEP_TAB_BAR_STYLE)
        self.tool_tabs.addTab(self.settings_panel, "Segmentation")
        self.tool_tabs.addTab(self.compartment_panel, "Compartment")
        self.tool_panel = self.tool_tabs
        return self.tool_panel

    def _build_viewer_actions(self, layout: QHBoxLayout) -> None:
        """
        Build viewer actions.
        """
        self.preview_actions = QWidget()
        actions_layout = QVBoxLayout(self.preview_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.addWidget(self.settings_panel.run_button)
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet("QPushButton { background: #a52a2a; color: white; font-weight: bold; padding: 7px; }")
        self.close_button.clicked.connect(self.close)
        self.settings_panel.apply_button.setText("Save current settings")
        self.settings_panel.apply_button.setStyleSheet("QPushButton { background: #16803b; color: white; font-weight: bold; padding: 7px; }")
        actions_layout.addWidget(self.settings_panel.apply_button)
        actions_layout.addWidget(self.close_button)
        layout.addStretch(1)
        layout.addWidget(self.preview_actions)

    def _set_source_controls_enabled(self, enabled: bool) -> None:
        """
        Set source controls enabled.
        """
        super()._set_source_controls_enabled(enabled)
        self.settings_panel.run_button.setEnabled(enabled)
        self.settings_panel.apply_button.setEnabled(enabled)
        self.close_button.setEnabled(True)

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        """
        Build overlay controls.
        """
        self.mask_colour = MaskColourControl()
        layout.addWidget(self.mask_colour)
        self.mask_colour.colour_changed.connect(self._mask_colour_changed)

    def _connect_tools(self) -> None:
        """
        Connect tools.
        """
        self.mode_label = QLabel("Segmentation — cell masks")
        self.mode_label.setWordWrap(True)
        image_parent = self.image_viewer.parentWidget()
        assert image_parent is not None
        image_layout = image_parent.layout()
        assert isinstance(image_layout, QVBoxLayout)
        image_layout.insertWidget(0, self.mode_label)
        self.tool_tabs.currentChanged.connect(self._tab_changed)
        self.compartment_panel.changed.connect(self._compartment_edited)
        self.compartment_panel.mask_channels.currentRowChanged.connect(self._mask_channel_changed)
        self.diameter_reference = DiameterReference(self.image_viewer.view_box, self.image_viewer.image_item)
        self.settings_panel.diameter.valueChanged.connect(self.diameter_reference.set_diameter)
        self.diameter_reference.set_diameter(self.settings_panel.diameter.value())
        self.settings_panel.run_requested.connect(self._run_preview)
        self.settings_panel.apply_requested.connect(self._apply_settings)
        self.settings_panel.mask_visibility_changed.connect(self.image_viewer.set_mask_visible)
        self.settings_panel.mask_opacity_changed.connect(self.image_viewer.set_mask_opacity)

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        """
        Tool keypress.
        """
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
        """
        Path selected.
        """
        if not isinstance(selected, (str, Path)):
            return
        source = Path(selected)
        if source.is_dir():
            source = image_for(source) or source / FITS_ARRAY_NAME
            if source.is_file() and self.directory_browser.select_path(source):
                return
        if source.name not in IMAGE_NAMES or not source.is_file():
            self.status_label.setText("Select an experiment containing FITS image artifacts.")
            return
        self._open_source(source)

    def _open_source(self, source: Path) -> None:
        """
        Open source.
        """
        try:
            source = image_input_for(source, cst.StepName.SEGMENT) or source
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        if source == self._source_path:
            return
        if self._thread is not None:
            self.status_label.setText("Wait for the current preview before changing experiment.")
            return
        self._close_session()
        try:
            baseline = self._settings_for_source(source)
            self._segmentation_session = SegmentationTuningSession(source)
            labels = self._segmentation_session.channel_labels
            entries = self._entries or (baseline.channels if baseline is not None else [])
            missing = [entry.channel for entry in entries if entry.channel not in labels]
            if missing:
                raise ValueError(f"Configured channels are missing from this image: {', '.join(missing)}.")
            self._entries = [entry.model_copy(deep=True) for entry in entries]
            if not self._entries:
                self._entries = [SegmentChannelSettings(channel=labels[0])]
            self._entry_index = min(self._entry_index, len(self._entries) - 1)
            self._segmentation_session.set_segment_settings(self._entries[self._entry_index])
        except Exception as error:
            if self._segmentation_session is not None:
                self._segmentation_session.close()
            self._segmentation_session = None
            self.status_label.setText(str(error))
            return
        self._source_path = source
        if self._save_root is None:
            self._save_root = source.parent
        self._refresh_mask_channels()
        self._image_session = self._segmentation_session
        self.frame_slider.setRange(0, self._segmentation_session.frame_count - 1)
        self.z_slider.setRange(0, self._segmentation_session.plane_count - 1)
        self.frame_slider.setValue(0)
        self.z_slider.setValue(0)
        self._set_source_controls_enabled(True)
        self._load_entry()
        if not self._saved_baseline_set:
            self._saved_entries = [entry.model_copy(deep=True) for entry in self._entries]
            self._saved_baseline_set = True
        self.status_label.setText(
            f"Loaded {source.parent.name} — axes "
            f"{self._segmentation_session.axes}, shape {self._segmentation_session.shape}.")
        self._model_change_timer.stop()
        if self._requested_tab == "compartment":
            self.tool_tabs.setCurrentIndex(1)
        if self.image_viewer._mask_array is None:
            self._initialize_selected_model()
            self._automatic_preview = True
            QTimer.singleShot(0, self._run_preview_when_ready)

    def _settings_for_source(self, source: Path) -> SegmentSettings | None:
        """
        Settings for source.
        """
        if self._provided_settings is not None:
            return self._provided_settings
        root = self.directory_browser.root_path
        for directory in (source.parent, *source.parents):
            settings_path = run_settings_path(directory)
            if settings_path.is_file():
                adapter = SettingsAdapter()
                adapter.load(settings_path)
                self._save_root = directory
                if not self._extract_provided:
                    self._extract_settings = ExtractSettings.model_validate(adapter.as_mapping()[cst.StepName.EXTRACT]["params"])
                    self.compartment_panel.set_settings(self._extract_settings)
                return adapter.segmentation_settings()
            if root is not None and directory == root:
                break
        return None

    def _display_overlay(self, image: NDArray[Any], frame: int, channel: str, z_index: int) -> None:
        """
        Display a saved or temporary mask independently of the image channel.
        """
        self.diameter_reference.set_diameter(0 if self._in_compartment() else self.settings_panel.diameter.value())
        self.image_viewer.set_drawing_enabled(False)
        if self._segmentation_session is None or self._loading_entry or self._source_path is None:
            return
        settings = self._preview_channel_settings()
        if not self._in_compartment():
            settings = self._entries[self._entry_index]
        source = saved_mask_path(self._source_path.parent, compartment=self._in_compartment())
        result = self._mask_previews.mask(source, frame, settings.channel, z_index, settings)
        if result is None:
            self.compartment_panel.source_label.setText("No mask available — run preview")
            return
        mask, revision, description, stale = result
        if self._in_compartment():
            mask = self._mask_previews.membrane(mask, revision,
                self.compartment_panel.thickness.value(), self.compartment_panel.dilation.value())
        self.image_viewer.set_mask(mask)
        self.compartment_panel.source_label.setText(description)
        self.mode_label.setText(("Compartment — membrane rings" if self._in_compartment()
                                else "Segmentation — cell masks") + " | " + description)
        if stale:
            self.status_label.setText("Preview out of date — run preview to use the changed segmentation settings.")

    def _clear_tools(self) -> None:
        """
        Clear tools.
        """
        self.diameter_reference.hide()
        self._automatic_preview = False
        self._mask_previews.close()
        if self._segmentation_session is not None:
            self._segmentation_session.close()
        self._segmentation_session = None

    @Slot()
    def _run_preview(self) -> None:
        """
        Run preview.
        """
        self.show_mask.setChecked(True)
        if self._segmentation_session is None or self._thread is not None:
            return
        try:
            settings = self._preview_channel_settings()
            self._segmentation_session.set_segment_settings(settings)
        except Exception as error:
            self.status_label.setText(f"Invalid Cellpose settings: {error}")
            return
        request = PreviewRequest(frame_index=self.frame_slider.value(),
                                 channel=settings.channel,
                                 z_index=self.z_slider.value(),
                                 user_settings=dict(settings.user_settings),
                                 )
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
        self.status_label.setText(f"Running Cellpose on frame {request.frame_index + 1}, {request.channel}…")
        self._thread.start()

    @Slot()
    def _initialize_selected_model(self) -> None:
        """
        Initialize selected model.
        """
        if self._segmentation_session is None:
            return
        try:
            settings = self.current_channel_settings()
        except Exception as error:
            self.status_label.setText(f"Invalid Cellpose settings: {error}")
            return
        if self._thread is not None:
            self._pending_model_settings = settings
            self.status_label.setText("Model selection changed; the latest model will initialize next.")
            return
        self._start_model_initialization(settings)

    def _start_model_initialization(self, settings: SegmentChannelSettings) -> None:
        """
        Start model initialization.
        """
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
        """
        Model initialized.
        """
        del request
        self.status_label.setText("Cellpose model ready. Adjust settings or run a preview.")

    @Slot(object, str)
    def _model_initialization_failed(self, request: ModelInitializationRequest, message: str) -> None:
        """
        Model initialization failed.
        """
        del request
        self.status_label.setText(f"Cellpose model initialization failed: {message}")

    @Slot(object)
    def _preview_finished(self, outcome: PreviewOutcome) -> None:
        """
        Preview finished.
        """
        if outcome.request != self._active_request or self._segmentation_session is None:
            return
        try:
            self._display_preview_mask(outcome.preview, outcome.request.z_index)
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        produced = next((entry for entry in self._entries if entry.channel == outcome.request.channel),
                        self._segmentation_session.segment_settings)
        self._mask_previews.remember(outcome.preview, produced, outcome.request.z_index)
        self._display_selection()
        cache_note = "loaded from preview cache" if outcome.preview.from_cache else "segmented"
        self.status_label.setText(f"Frame {outcome.request.frame_index + 1}, {outcome.request.channel}: {cache_note}.",
                                  )

    def _display_preview_mask(self, preview: SegmentationPreview, z_index: int) -> None:
        """
        Display preview mask.
        """
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
        """
        Preview failed.
        """
        self.status_label.setText(f"Cellpose preview failed: {message}")

    @Slot()
    def _thread_finished(self) -> None:
        """
        Thread finished.
        """
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
        elif self._automatic_preview:
            QTimer.singleShot(0, self._run_preview_when_ready)

    @Slot()
    def _apply_settings(self) -> None:
        """
        Save every entry belonging to the active tab without closing the tuner.
        """
        if self._thread is not None:
            self.status_label.setText("Wait for the current operation before saving settings.")
            return
        try:
            if self._in_compartment():
                settings = self.compartment_panel.settings(self._extract_settings)
                if self._standalone:
                    self._persist_settings(settings)
                self.compartment_settings_applied.emit(settings)
                self._extract_settings = settings
                self.status_label.setText("Compartment settings saved to Quantification.")
            else:
                settings = self.current_settings()
                if self._standalone:
                    self._persist_settings(settings)
                self.settings_applied.emit(settings)
                self._provided_settings = settings
                self._saved_entries = [entry.model_copy(deep=True) for entry in settings.channels]
                self.status_label.setText("All segmentation channel settings saved.")
        except (ValueError, OSError, RuntimeError) as error:
            self.status_label.setText(f"Cannot save settings: {error}")

    def current_settings(self) -> SegmentSettings:
        """
        Current settings.
        """
        if self._segmentation_session is None:
            raise RuntimeError("Load an experiment before applying settings.")
        self._commit_entry()
        baseline = self._provided_settings or SegmentSettings()
        return SegmentSettings(channels=[entry.model_copy(deep=True) for entry in self._entries],
                               overwrite=baseline.overwrite,
                               execution=baseline.execution,
                               workers=baseline.workers,
                               ordered_execution=baseline.ordered_execution,
                               )

    def current_channel_settings(self) -> SegmentChannelSettings:
        """
        Return the complete validated settings represented by the viewer.
        """
        if self._segmentation_session is None:
            raise RuntimeError("Load an experiment before applying settings.")
        payload: dict[str, Any] = self._segmentation_session.segment_settings.model_dump()
        payload["channel"] = (self._entries[self._entry_index].channel if self._in_compartment()
                              else self.channel_combo.currentText())
        payload["nuclear_channel"] = self.settings_panel.selected_nuclear_channel
        payload["do_denoise"] = self.settings_panel.denoise.isChecked()
        payload["user_settings"] = {
            **self._segmentation_session.segment_settings.user_settings,
            **self.settings_panel.user_settings(),}
        return SegmentChannelSettings.model_validate(payload)

    def _commit_entry(self) -> None:
        """
        Commit entry.
        """
        if self._segmentation_session is not None and not self._loading_entry and not self._in_compartment():
            self._entries[self._entry_index] = self.current_channel_settings()

    def _settings_edited(self, *args: Any) -> None:
        """
        Settings edited.
        """
        if self._in_compartment() or self._loading_entry or self._segmentation_session is None or not self.channel_combo.currentText():
            return
        self._commit_entry()
        self._display_selection()
        item = self.channel_settings_list.item(self._entry_index)
        if item is not None:
            row = self.channel_settings_list.itemWidget(item)
            entry = self._entries[self._entry_index]
            row.findChildren(QPushButton)[0].setText(
                f"{entry.channel} | {entry.user_settings.get('model_type', 'default')} | "
                f"diameter {entry.user_settings.get('diameter', 15)}")

    def _refresh_entries(self) -> None:
        """
        Refresh entries.
        """
        self.channel_settings_list.blockSignals(True)
        self.channel_settings_list.clear()
        for index, entry in enumerate(self._entries):
            item = QListWidgetItem()
            self.channel_settings_list.addItem(item)
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 0, 4, 0)
            label = QPushButton(
                f"{entry.channel} | {entry.user_settings.get('model_type', 'default')} | "
                f"diameter {entry.user_settings.get('diameter', 15)}")
            label.setCheckable(True)
            label.setChecked(index == self._entry_index)
            label.clicked.connect(lambda checked=False, i=index: self.channel_settings_list.setCurrentRow(i))
            layout.addWidget(label, 1)
            remove = QPushButton("🗑")
            remove.setFixedWidth(28)
            remove.setToolTip(f"Remove settings for {entry.channel}")
            remove.setEnabled(len(self._entries) > 1)
            remove.clicked.connect(lambda checked=False, i=index: self._remove_entry(i))
            layout.addWidget(remove)
            item.setSizeHint(row.sizeHint())
            self.channel_settings_list.setItemWidget(item, row)
        self.channel_settings_list.setCurrentRow(self._entry_index)
        self.channel_settings_list.blockSignals(False)
        labels = self._segmentation_session.channel_labels if self._segmentation_session else ()
        self.add_channel_button.setEnabled(len(self._entries) < len(labels) and self._thread is None)

    def _load_entry(self) -> None:
        """
        Load entry.
        """
        if self._segmentation_session is None:
            return
        self._loading_entry = True
        try:
            entry = self._entries[self._entry_index]
            self._segmentation_session.set_segment_settings(entry)
            self.settings_panel.set_settings(entry)
            self.settings_panel.set_3d_available(self._segmentation_session.plane_count > 1)
            labels = self._segmentation_session.channel_labels
            self.settings_panel.set_channels(labels, entry.nuclear_channel)
            used = {value.channel for i, value in enumerate(self._entries)
                    if i != self._entry_index}
            self.channel_combo.blockSignals(True)
            self.channel_combo.clear()
            self.channel_combo.addItems(list(labels) if self._in_compartment() else [label for label in labels if label not in used])
            self.channel_combo.setCurrentText(entry.channel)
            self.channel_combo.blockSignals(False)
        finally:
            self._loading_entry = False
        self._refresh_entries()
        self._refresh_mask_channels()
        self._display_selection()

    def _select_entry(self, index: int) -> None:
        """
        Select entry.
        """
        if index < 0 or index == self._entry_index:
            return
        if self._thread is not None:
            self._refresh_entries()
            return
        self._entry_index = index
        self._load_entry()
        self._model_change_timer.start()

    def _add_channel(self) -> None:
        """
        Add channel.
        """
        if self._thread is not None or self._segmentation_session is None:
            return
        used = {entry.channel for entry in self._entries}
        available = [label for label in self._segmentation_session.channel_labels if label not in used]
        if not available:
            return
        entry = self._entries[self._entry_index].model_copy(deep=True)
        entry.channel = available[0]
        self._entries.append(entry)
        self._entry_index = len(self._entries) - 1
        self._load_entry()
        self._model_change_timer.start()

    def _remove_entry(self, index: int) -> None:
        """
        Remove entry.
        """
        if self._thread is not None or len(self._entries) <= 1:
            return
        removed = self._entries.pop(index).channel
        self._saved_entries = [entry for entry in self._saved_entries if entry.channel != removed]
        if self._provided_settings is not None:
            self._provided_settings.channels = [entry for entry in self._provided_settings.channels if entry.channel != removed]
        self.channel_removed.emit(removed)
        if self._standalone:
            self._persist_settings(SegmentSettings(channels=self._saved_entries))
        if index < self._entry_index:
            self._entry_index -= 1
        self._entry_index = min(self._entry_index, len(self._entries) - 1)
        self._load_entry()
        self._model_change_timer.start()

    def _set_running(self, running: bool, *, initialization: bool = False) -> None:
        """
        Set running.
        """
        self.progress.setVisible(running)
        self.tool_tabs.tabBar().setEnabled(not running)
        self.compartment_panel.mask_channels.setEnabled(not running)
        self.channel_settings_list.setEnabled(not running)
        self.add_channel_button.setEnabled(
            not running and self._segmentation_session is not None
            and len(self._entries) < len(self._segmentation_session.channel_labels))
        if initialization:
            self.settings_panel.run_button.setEnabled(not running)
            return
        self.settings_panel.set_running(running)
        self._set_directory_controls_enabled(not running)
        self.directory_browser.setEnabled(not running)
        self.frame_slider.setEnabled(not running)
        self.channel_combo.setEnabled(not running)
        self.z_slider.setEnabled(not running)

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Stop active work and handle the window close event.
        """
        if self._thread is not None:
            activity = ("model initialization"
                        if self._active_operation == "initialization"
                        else "preview")
            self.status_label.setText(f"Wait for the current Cellpose {activity} before closing.")
            event.ignore()
            return
        if self._has_unsaved_settings():
            decision = QMessageBox.question(self, "Unsaved settings",
                "Some settings have not been saved to the main window. Discard these changes and close?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if decision != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        super().closeEvent(event)
        self._model_change_timer.stop()

    def _in_compartment(self) -> bool:
        """
        Return whether the compartment tab currently owns the viewer.
        """
        return hasattr(self, "tool_tabs") and self.tool_tabs.currentIndex() == 1

    def _preview_channel_settings(self) -> SegmentChannelSettings:
        """
        Resolve mask-producing settings independently of the fluorescence background.
        """
        if not self._in_compartment():
            return self.current_channel_settings()
        item = self.compartment_panel.mask_channels.currentItem()
        label = item.text() if item is not None else self._entries[self._entry_index].channel
        return next((entry.model_copy(deep=True) for entry in self._entries if entry.channel == label),
                    SegmentChannelSettings(channel=label))

    def _refresh_mask_channels(self) -> None:
        """
        List available mask identities without add/remove actions on this tab.
        """
        if self._source_path is None:
            return
        source = saved_mask_path(self._source_path.parent, compartment=True)
        try:
            labels = list(self._mask_previews.channels(source))
        except (OSError, ValueError) as error:
            self.status_label.setText(f"Cannot load saved mask: {error}")
            labels = []
        if not labels:
            labels = [entry.channel for entry in self._entries]
        labels.extend(channel for _, channel, _ in self._mask_previews.previews if channel not in labels)
        control = self.compartment_panel.mask_channels
        selected = control.currentItem().text() if control.currentItem() is not None else None
        control.blockSignals(True)
        control.clear()
        control.addItems(labels)
        control.setCurrentRow(labels.index(selected) if selected in labels else 0)
        control.blockSignals(False)

    def _mask_channel_changed(self, index: int) -> None:
        """
        Change only the mask geometry while retaining the image background channel.
        """
        if self._in_compartment():
            self._display_selection()

    def _compartment_edited(self) -> None:
        """
        Redraw using cached geometry when only membrane thickness changes.
        """
        if self._in_compartment() and self._thread is None:
            self._display_selection()

    def _tab_changed(self, index: int) -> None:
        """
        Preserve each tab's controls, image channel, and mask colour selection.
        """
        self._mask_colours[self._last_tab] = self.mask_colour.selection()
        self._last_tab = index
        self.mask_colour.set_selection(self._mask_colours[index])
        if self._segmentation_session is not None:
            if index == 1:
                selected = self.channel_combo.currentText()
                self.channel_combo.blockSignals(True)
                self.channel_combo.clear()
                self.channel_combo.addItems(self._segmentation_session.channel_labels)
                self.channel_combo.setCurrentText(selected)
                self.channel_combo.blockSignals(False)
                self._refresh_mask_channels()
            else:
                self._load_entry()
        self._apply_tab_appearance()
        self._display_selection()

    def _apply_tab_appearance(self) -> None:
        """
        Match REF/ROI backgrounds and title badges with workflow-style subtabs.
        """
        background, accent, badge = (("#182e27", "#82d5b1", "#254c3c") if self._in_compartment()
                                     else ("#172635", "#80b9f2", "#243e58"))
        central = self.centralWidget()
        palette = central.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(background))
        central.setPalette(palette)
        central.setAutoFillBackground(True)
        self.mode_label.setText("Compartment — membrane rings" if self._in_compartment()
                                else "Segmentation — cell masks")
        self.mode_label.setStyleSheet(f"background: {badge}; color: {accent}; border-left: 5px solid {accent}; "
                                      "padding: 4px 8px; font-weight: bold; font-size: 14px;")
        self.diameter_reference.set_diameter(0 if self._in_compartment() else self.settings_panel.diameter.value())

    def _mask_colour_changed(self, colour: QColor | None) -> None:
        """
        Update only the display overlay, leaving geometry and unsaved state alone.
        """
        self.image_viewer.set_mask_color(colour)

    def _has_unsaved_settings(self) -> bool:
        """
        Compare both processing tabs with their most recently saved values.
        """
        if self._segmentation_session is None:
            return False
        return (self._entries != self._saved_entries
                or self.compartment_panel.settings(self._extract_settings) != self._extract_settings)

    def _persist_settings(self, settings: SegmentSettings | ExtractSettings) -> None:
        """
        Save standalone edits through the normal comment-preserving settings adapter.
        """
        root = self._save_root or self.directory_browser.root_path
        if root is None:
            raise ValueError("Select a run directory before saving settings.")
        path = run_settings_path(root)
        adapter = SettingsAdapter()
        if path.is_file():
            adapter.load(path)
        adapter.run_dir = str(root)
        if isinstance(settings, SegmentSettings):
            adapter.set_segment_channels([entry.to_payload_dict() for entry in settings.channels])
        else:
            for name in ("compartments", "membrane_thickness", "dilation_radius", "save_compartment_masks"):
                adapter.set_field_value(cst.StepName.EXTRACT, name, getattr(settings, name))
        adapter.save(path)

    def _run_preview_when_ready(self) -> None:
        """
        Generate an initial segmentation only when no saved mask can be displayed.
        """
        if self._automatic_preview and self._thread is None and self._segmentation_session is not None:
            self._automatic_preview = False
            self._run_preview()
