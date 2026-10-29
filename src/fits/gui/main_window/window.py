from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget

from fits.environment import constant as cst
from fits.environment.paths import reports_dir
from fits.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage
from fits.workflows.runtime.interactive.messages import TrackEditRequest, TrackEditOutcome
from fits.gui.settings import STEP_LAYOUTS, RuntimeSettingsEditor, SettingsAdapter, StepSettingsEditor
from fits.gui.main_window.report_dialog import ReportDialog
from fits.gui.main_window.run_browser import RunDirectoryBrowser
from fits.gui.main_window.logging import LogEmitter, QtLogHandler
from fits.gui.main_window.pipeline_worker import PipelineWorker
from fits.gui.main_window.progress_display import PipelineProgressWidget
from fits.settings.models import BGSubSettings, RegisterChannelSettings, RegisterTimeSettings, SegmentSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.settings.loader import run_settings_path


_PHASE_STEPS = (
    ("Convert", (cst.StepName.CONVERT,)),
    ("Preprocess", (cst.StepName.REGISTER_TIME, cst.StepName.REGISTER_CHANNEL, cst.StepName.BG_SUB)),
    ("Process", (cst.StepName.SEGMENT, cst.StepName.TRACK, cst.StepName.EDIT_TRACK)),
    ("Analysis", (cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE)),
)
_STEP_PHASE = {step: phase_index
                for phase_index, (_, steps) in enumerate(_PHASE_STEPS)
                for step in steps}


class FitsMainWindow(QMainWindow):
    """Main FITS desktop window."""

    def __init__(self,
                adapter: SettingsAdapter | None = None,
                parent: QWidget | None = None,
                demo_step_delay: float = 0.0,
                ) -> None:
        super().__init__(parent)
        self.demo_step_delay = demo_step_delay
        self._mask_collection = None
        self._mask_expected_count: int | None = None
        self._track_edit_queue: list[TrackEditRequest] = []
        self._tracking_editor = None
        self._run_progress: RunProgress | None = None
        self.adapter = adapter or SettingsAdapter()
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        self._running = False
        self._current_step = cst.StepName.CONVERT
        self._conversion_root: str | None = None
        self._converted_settings: dict | None = None
        self._pending_conversion: dict | None = None
        self._advance_after_conversion = False
        self._conversion_run = False
        self._editors: dict[cst.StepName, StepSettingsEditor] = {}
        self.runtime_editor: RuntimeSettingsEditor | None = None
        self._segmentation_tuner = None
        self._background_tuner = None
        self._registration_tuner = None
        self._registration_tune_buttons: dict[cst.StepName, QPushButton] = {}
        self._tracking_viewer = None
        self._channel_labels_window = None
        self._prepared_available = False
        self._phases_unlocked = False
        self._populating_settings = False
        self._settings_population_generation = 0

        self.setWindowTitle("FITS")
        self.setAcceptDrops(True)
        self.resize(1200, 850)
        self._build_ui()
        self._populate_from_adapter()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setAutoFillBackground(True)
        outer = QVBoxLayout(central)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        identity_panel = QWidget()
        identity = QVBoxLayout(identity_panel)
        identity.setContentsMargins(0, 0, 8, 0)
        identity_form = QFormLayout()

        run_dir_row = QWidget()
        run_dir_layout = QHBoxLayout(run_dir_row)
        run_dir_layout.setContentsMargins(0, 0, 0, 0)
        self.run_dir_edit = QLineEdit()
        self.run_dir_edit.setAcceptDrops(False)
        self.run_dir_edit.setPlaceholderText("Browse or drop a folder here…")
        run_dir_tooltip = (
            "Choose or drag and drop a folder containing this FITS run. "
            "FITS reads or saves its settings in "
            ".fits and writes run outputs here."
        )
        self.run_dir_edit.setToolTip(run_dir_tooltip)
        self.run_dir_edit.returnPressed.connect(self._run_dir_entered)
        self.run_dir_edit.textChanged.connect(self._run_dir_text_changed)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setToolTip("Choose the folder containing this FITS run.")
        self.browse_button.clicked.connect(self._browse_run_dir)
        run_dir_layout.addWidget(self.run_dir_edit)
        run_dir_layout.addWidget(self.browse_button)
        run_dir_label = QLabel("Run directory")
        run_dir_label.setToolTip(run_dir_tooltip)
        identity_form.addRow(run_dir_label, run_dir_row)

        self.user_name_edit = QLineEdit()
        user_name_tooltip = "Name recorded with this run's settings."
        self.user_name_edit.setToolTip(user_name_tooltip)
        user_name_label = QLabel("User name")
        user_name_label.setToolTip(user_name_tooltip)
        identity_form.addRow(user_name_label, self.user_name_edit)
        identity.addLayout(identity_form)

        self.runtime_host = QWidget()
        self.runtime_host_layout = QVBoxLayout(self.runtime_host)
        self.runtime_host_layout.setContentsMargins(0, 6, 0, 0)
        identity.addWidget(self.runtime_host)
        identity.addStretch()
        top_splitter.addWidget(identity_panel)

        self.run_browser = RunDirectoryBrowser()
        self.run_browser.path_activated.connect(self._open_selected_report)
        self.tracking_viewer_button = QPushButton("Tracking Viewer")
        self.tracking_viewer_button.setToolTip(
            "Inspect tracked cells, masks and trajectories in the selected experiment, "
            "or the first tracking result in the run. If none exist, show how to create them.")
        self.tracking_viewer_button.setStyleSheet(
            "QPushButton { background-color: #d97706; color: white; font-weight: bold; } "
            "QPushButton:disabled { background-color: #6b4b2a; color: #aaa; }")
        self.tracking_viewer_button.clicked.connect(
            lambda: self._open_tracking_viewer())
        self.run_browser.selection_layout.addWidget(self.tracking_viewer_button)
        self.channel_labels_button = QPushButton("Edit Channel Labels")
        self.channel_labels_button.setToolTip(
            "Inspect and rename channel labels across this run's converted images, "
            "masks, measurement tables and settings.")
        self.channel_labels_button.clicked.connect(self._open_channel_labels)
        self.run_browser.selection_layout.addWidget(self.channel_labels_button)
        self.report_button = QPushButton("Full Report")
        self.report_button.setToolTip(
            "Open the latest run report with completed, skipped and failed work. "
            "If no report exists, show how to create one.")
        self.report_button.clicked.connect(self._open_latest_report)
        self.run_browser.selection_layout.addWidget(self.report_button)
        top_splitter.addWidget(self.run_browser)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 2)
        top_splitter.setSizes([470, 690])
        outer.addWidget(top_splitter)

        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(6)
        self.page_title = QLabel("1 · Convert your images")
        self.page_title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 4px 0;")
        settings_layout.addWidget(self.page_title)
        self.workflow_pages = QStackedWidget()
        self.convert_tabs = QTabWidget()
        self.workflow_pages.addWidget(self.convert_tabs)
        self.phase_tabs = QTabWidget()
        main_tab_style = (
            "QTabBar::tab { font-size: 17px; font-weight: bold; padding: 7px 26px; "
            "color: #cedbe7; background: #26384b; border: 1px solid #476580; "
            "border-top-left-radius: 12px; border-top-right-radius: 12px; margin-right: 6px; }"
            "QTabBar::tab:selected { color: white; background: #494949; "
            "border-color: #6fc5ff; border-bottom-color: #494949; }"
            "QTabBar::tab:hover:!selected { background: #334e67; }")
        for main_tabs in (self.convert_tabs, self.phase_tabs):
            main_tabs.setObjectName("mainWorkflowTabs")
            main_tabs.setStyleSheet(
                "QTabWidget#mainWorkflowTabs::pane { border: 1px solid #476580; "
                "background: #494949; top: -1px; }")
            main_tabs.tabBar().setStyleSheet(main_tab_style)
        self._step_tabs: dict[int, QTabWidget] = {}
        for phase, (title, _) in enumerate(_PHASE_STEPS[1:], start=1):
            tabs = QTabWidget()
            tabs.setObjectName("stepSettingsTabs")
            tabs.setStyleSheet(
                "QTabWidget#stepSettingsTabs::pane { border: 1px solid #626262; "
                "background: #383838; top: -1px; }")
            tabs.tabBar().setStyleSheet(
                "QTabBar::tab { font-size: 12px; font-weight: normal; padding: 5px 16px; "
                "color: #bfc5cc; background: #292929; border: 1px solid #626262; "
                "border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 5px; }"
                "QTabBar::tab:selected { color: #a8dcff; background: #383838; "
                "border-color: #82b4d6; border-bottom-color: #383838; }"
                "QTabBar::tab:hover:!selected { background: #323232; }")
            tabs.currentChanged.connect(lambda index, p=phase: self._substep_selected(p, index))
            self._step_tabs[phase] = tabs
            phase_page = QWidget()
            phase_layout = QVBoxLayout(phase_page)
            phase_layout.setContentsMargins(10, 12, 10, 10)
            phase_layout.addWidget(tabs)
            self.phase_tabs.addTab(phase_page, title)
        self.phase_tabs.currentChanged.connect(self._phase_selected)
        self.workflow_pages.addWidget(self.phase_tabs)
        settings_layout.addWidget(self.workflow_pages, 1)

        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        vertical_splitter.addWidget(settings_panel)

        console_container = QWidget()
        console_layout = QVBoxLayout(console_container)
        console_layout.setContentsMargins(0, 0, 0, 0)
        activity_header = QHBoxLayout()
        activity_label = QLabel("Activity log")
        activity_label.setFixedWidth(230)
        activity_header.addWidget(activity_label)
        self.pipeline_progress = PipelineProgressWidget()
        self.pipeline_progress.setMinimumHeight(44)
        activity_header.addWidget(self.pipeline_progress, 1)
        console_layout.addLayout(activity_header)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(2_000)
        console_layout.addWidget(self.console)
        vertical_splitter.addWidget(console_container)
        vertical_splitter.setStretchFactor(0, 2)
        vertical_splitter.setStretchFactor(1, 1)
        vertical_splitter.setSizes([390, 180])
        outer.addWidget(vertical_splitter)

        buttons = QHBoxLayout()
        self.load_button = QPushButton("Load settings")
        self.save_button = QPushButton("Save settings")
        self.run_button = QPushButton("Run pipeline")
        self.load_button.clicked.connect(self._load_settings)
        self.save_button.clicked.connect(self._save_settings)
        self.run_button.clicked.connect(self._primary_action)
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch()
        self.navigation_status = QLabel()
        self.navigation_status.setStyleSheet("color: #b8b8b8;")
        buttons.addWidget(self.navigation_status)
        self.back_button = QPushButton("Back")
        self.back_button.setToolTip(
            "Return to Convert settings without running the pipeline. "
            "Your current processing settings are kept.")
        self.back_button.clicked.connect(self._back_to_convert)
        buttons.addWidget(self.back_button)
        self.activity_indicator = QProgressBar()
        self.activity_indicator.setFixedSize(160, 10)
        self.activity_indicator.setTextVisible(False)
        self.activity_indicator.setToolTip("Pipeline active — this is an activity indicator, not measured progress.")
        self.activity_indicator.setStyleSheet(
            "QProgressBar { background: #233040; border: 1px solid #405773; border-radius: 3px; }"
            "QProgressBar::chunk { background: #399df2; border-radius: 2px; }")
        self.activity_indicator.setRange(0, 1)
        self.activity_indicator.setValue(0)
        self.activity_indicator.hide()
        buttons.addWidget(self.activity_indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons.addWidget(self.run_button)
        outer.addLayout(buttons)

        self.setCentralWidget(central)

    def _populate_from_adapter(self) -> None:
        self._begin_settings_population()
        self.run_dir_edit.setText(self.adapter.run_dir)
        self.user_name_edit.setText(self.adapter.user_name)
        self.run_browser.set_root(self.adapter.run_dir)
        self._refresh_report_button()

        previous_step = self._current_step
        self.convert_tabs.clear()
        for tabs in self._step_tabs.values():
            tabs.clear()
        if self.runtime_editor is not None:
            self.runtime_host_layout.removeWidget(self.runtime_editor)
            self.runtime_editor.deleteLater()
        for editor in self._editors.values():
            editor.deleteLater()
        self._editors.clear()
        self._registration_tune_buttons.clear()

        self.runtime_editor = RuntimeSettingsEditor(self.adapter)
        self.runtime_editor.value_changed.connect(self._refresh_phase_access)
        self.runtime_host_layout.addWidget(self.runtime_editor)

        for step in (step for _, steps in _PHASE_STEPS for step in steps):
            editor = StepSettingsEditor(self.adapter, step)
            editor.value_changed.connect(self._update_run_button_text)
            editor.enabled_changed.connect(self._refresh_phase_markers)
            if step in (cst.StepName.REGISTER_TIME, cst.StepName.REGISTER_CHANNEL):
                tune_row = QWidget()
                tune_layout = QHBoxLayout(tune_row)
                tune_layout.setContentsMargins(0, 0, 0, 0)
                operation = "frame-shift registration" if step == cst.StepName.REGISTER_TIME else "channel-shift registration"
                preview_description = f"Preview {operation} and save this experiment's settings and transforms."
                description = QLabel(preview_description)
                description.setWordWrap(True)
                description.setToolTip(preview_description)
                tune_layout.addWidget(description, 1)
                tune_button = QPushButton("Preview")
                tune_button.setToolTip(
                    f"Preview {operation}. Requires a converted fits_array.tif image.")
                mode = "time" if step == cst.StepName.REGISTER_TIME else "channel"
                tune_button.clicked.connect(lambda checked=False, selected=mode: self._open_registration_tuner(selected))
                tune_layout.addWidget(tune_button)
                self._registration_tune_buttons[step] = tune_button
                editor.outer_layout.insertWidget(1, tune_row)
            if step == cst.StepName.BG_SUB:
                tune_row = QWidget()
                tune_layout = QHBoxLayout(tune_row)
                tune_layout.setContentsMargins(0, 0, 0, 0)
                tune_layout.setSpacing(16)
                self.bgtune_button = QPushButton("Preview")
                self.bgtune_button.setToolTip(
                    "Preview background subtraction on selected image planes and compare intensities. "
                    "Requires a converted fits_array.tif image.")
                self.bgtune_button.clicked.connect(self._open_background_tuner)
                tune_description = QLabel(
                    "Preview background subtraction on an image and compare intensities. "
                    "Save and close copies your changes back here.")
                tune_description.setWordWrap(True)
                tune_description.setToolTip(tune_description.text())
                tune_description.setStyleSheet("color: #b8b8b8;")
                tune_layout.addWidget(tune_description, 1)
                tune_layout.addWidget(
                    self.bgtune_button, 0, Qt.AlignmentFlag.AlignVCenter)
                editor.outer_layout.insertWidget(1, tune_row)
            if step == cst.StepName.SEGMENT:
                tune_row = QWidget()
                tune_layout = QHBoxLayout(tune_row)
                tune_layout.setContentsMargins(0, 0, 0, 0)
                tune_layout.setSpacing(16)
                self.segtune_button = QPushButton("Preview")
                self.segtune_button.setToolTip(
                    "Preview segmentation and adjust Cellpose settings. "
                    "Requires a converted fits_array.tif image in the run directory.")
                self.segtune_button.clicked.connect(self._open_segmentation_tuner)
                tune_description = QLabel(
                    "Preview segmentation on an image and adjust Cellpose settings. "
                    "Apply and close copies your changes back here.")
                tune_description.setWordWrap(True)
                tune_description.setToolTip(tune_description.text())
                tune_description.setStyleSheet("color: #b8b8b8;")
                tune_layout.addWidget(tune_description, 1)
                tune_layout.addWidget(
                    self.segtune_button, 0, Qt.AlignmentFlag.AlignVCenter)
                editor.outer_layout.insertWidget(1, tune_row)
            editor.set_editable(self.adapter.step_enabled(step))
            tabs = self.convert_tabs if step == cst.StepName.CONVERT else self._step_tabs[_STEP_PHASE[step]]
            tabs.addTab(editor, STEP_LAYOUTS[step].title)
            self._editors[step] = editor

        self._editors[cst.StepName.SEGMENT].value_changed.connect(
            self._editors[cst.StepName.TRACK].refresh_tracking_channels)

        self._refresh_phase_access()
        root = self._conversion_signature()["run_dir"]
        if root != self._conversion_root:
            self._conversion_root = root
            self._converted_settings = self._conversion_signature() if self._prepared_available else None
            previous_step = cst.StepName.REGISTER_TIME if self._prepared_available else cst.StepName.CONVERT
        elif previous_step != cst.StepName.CONVERT and not self._conversion_is_current():
            previous_step = cst.StepName.CONVERT
        self._show_step(previous_step)
        self._schedule_settings_population_finish()

    def _begin_settings_population(self) -> None:
        self._settings_population_generation += 1
        self._populating_settings = True

    def _schedule_settings_population_finish(self) -> None:
        generation = self._settings_population_generation
        QTimer.singleShot(
            0,
            lambda: self._finish_populating_settings(generation),
        )

    def _finish_populating_settings(self, generation: int) -> None:
        if generation == self._settings_population_generation:
            self._populating_settings = False

    @Slot()
    def _open_background_tuner(self) -> None:
        """Open background tuning with GUI settings and a fixed run directory."""
        from fits.gui.viewer.background import BackgroundTunerWindow

        if self._background_tuner is not None:
            self._background_tuner.show()
            self._background_tuner.raise_()
            return
        self._sync_identity()
        self._editors[cst.StepName.BG_SUB].sync_to_adapter()
        try:
            settings = BGSubSettings.model_validate(self.adapter.as_mapping()["bg_sub"]["params"])
        except ValueError as error:
            QMessageBox.critical(self, "Cannot open background tuner", str(error))
            return
        tuner = BackgroundTunerWindow(
            self.adapter.run_dir or None, settings=settings, directory_locked=True,
            initial_path=self.run_browser.selected_path, parent=self)
        tuner.setWindowModality(Qt.WindowModality.WindowModal)
        tuner.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tuner.settings_applied.connect(self._apply_background_settings)
        tuner.destroyed.connect(lambda: setattr(self, "_background_tuner", None))
        self._background_tuner = tuner
        tuner.show()

    def _tuner_expanded_sections(
        self, step: cst.StepName,
        settings: BGSubSettings | RegisterTimeSettings | RegisterChannelSettings,
    ) -> set[cst.StepName]:
        """Preserve open sections and reveal only changed advanced tuner values."""
        expanded = {name for name, editor in self._editors.items() if editor.advanced_settings_visible}
        current = type(settings).model_validate(self.adapter.as_mapping()[step]["params"])
        before, after = current.to_payload_dict(), settings.to_payload_dict()
        advanced = set(STEP_LAYOUTS[step].advanced)
        if isinstance(settings, (RegisterTimeSettings, RegisterChannelSettings)):
            assert isinstance(current, (RegisterTimeSettings, RegisterChannelSettings))
            previous = resolve_registration_plan(current.context, current.backend, current.method)
            effective = resolve_registration_plan(settings.context, settings.backend, settings.method)
            preset = resolve_registration_plan(settings.context)
            for field in ("backend", "method"):
                before[field] = getattr(previous, field)
                after[field] = getattr(effective, field)
            if effective == preset:
                advanced.difference_update(("backend", "method"))
        if any(before.get(field) != after[field] for field in advanced if field in after):
            expanded.add(step)
        return expanded

    @Slot(object)
    def _apply_background_settings(self, settings: BGSubSettings) -> None:
        """Transfer tuning parameters while preserving step-enabled and runtime states."""
        expanded = self._tuner_expanded_sections(cst.StepName.BG_SUB, settings)
        for key, value in {**settings.to_payload_dict(), "overwrite": settings.overwrite}.items():
            self.adapter.set_field_value(cst.StepName.BG_SUB, key, "None" if value is None else value)
        self._populate_from_adapter()
        for name in expanded:
            self._editors[name].show_advanced_settings()
        self._show_step(cst.StepName.BG_SUB)
        self._append_log("Applied background-subtraction settings from the tuner.")

    @Slot()
    def _open_segmentation_tuner(self) -> None:
        from fits.gui.viewer.segmentation import SegmentationTunerWindow

        self._sync_identity()
        self._editors[cst.StepName.SEGMENT].sync_to_adapter()
        try:
            settings = self.adapter.segmentation_settings(for_tuning=True)
        except ValueError as error:
            QMessageBox.critical(self, "Cannot open segmentation tuner", str(error))
            return
        tuner = SegmentationTunerWindow(experiments_dir=self.adapter.run_dir or None,
                                        segment_settings=settings,
                                        parent=self,
                                        initial_path=self.run_browser.selected_path,
                                        close_on_apply=True, directory_locked=True,)
        tuner.setWindowModality(Qt.WindowModality.WindowModal)
        tuner.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tuner.settings_applied.connect(self._apply_segmentation_settings)
        tuner.destroyed.connect(lambda: setattr(self, "_segmentation_tuner", None))
        self._segmentation_tuner = tuner
        tuner.show()

    def _open_registration_tuner(self, mode: str) -> None:
        from fits.gui.viewer.registration import RegistrationTunerWindow
        if self._registration_tuner is not None:
            self._registration_tuner.tabs.setCurrentIndex(0 if mode == "time" else 1)
            self._registration_tuner.show()
            self._registration_tuner.raise_()
            return
        self._sync_identity()
        for step in (cst.StepName.REGISTER_TIME, cst.StepName.REGISTER_CHANNEL):
            self._editors[step].sync_to_adapter()
        try:
            mapping = self.adapter.as_mapping()
            time_settings = RegisterTimeSettings.model_validate(mapping["register_time"]["params"])
            channel_settings = RegisterChannelSettings.model_validate(mapping["register_channel"]["params"])
        except ValueError as error:
            QMessageBox.critical(self, "Cannot open registration tuner", str(error))
            return
        tuner = RegistrationTunerWindow(
            self.adapter.run_dir or None, mode="time" if mode == "time" else "channel",
            time_settings=time_settings, channel_settings=channel_settings,
            initial_path=self.run_browser.selected_path, parent=self, directory_locked=True)
        tuner.setWindowModality(Qt.WindowModality.WindowModal)
        tuner.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tuner.settings_applied.connect(self._apply_registration_settings)
        tuner.destroyed.connect(lambda: setattr(self, "_registration_tuner", None))
        self._registration_tuner = tuner
        tuner.show()

    @Slot(str, object)
    def _apply_registration_settings(
        self, mode: str, settings: RegisterTimeSettings | RegisterChannelSettings,
    ) -> None:
        """Apply registration settings, revealing changed manual overrides only."""
        step = cst.StepName.REGISTER_TIME if mode == "time" else cst.StepName.REGISTER_CHANNEL
        expanded = self._tuner_expanded_sections(step, settings)
        for key, value in {**settings.to_payload_dict(), "overwrite": settings.overwrite}.items():
            self.adapter.set_field_value(step, key, "None" if value is None else value)
        self._populate_from_adapter()
        for name in expanded:
            self._editors[name].show_advanced_settings()
        self._show_step(step)
        self._append_log(f"Applied {mode} registration settings from the tuner.")

    @Slot(object)
    def _apply_segmentation_settings(self, settings: SegmentSettings) -> None:
        """Apply channel parameters without changing advanced-section visibility."""
        expanded = {name for name, editor in self._editors.items() if editor.advanced_settings_visible}
        self.adapter.set_segment_channels(
            [entry.to_payload_dict() for entry in settings.channels])
        self._populate_from_adapter()
        for name in expanded:
            self._editors[name].show_advanced_settings()
        self._show_step(cst.StepName.SEGMENT)
        self._append_log("Applied settings from the segmentation tuner.")

    def _show_step(self, step: cst.StepName) -> None:
        """Display one step without triggering navigation validation."""
        if step != cst.StepName.CONVERT and not self._phases_unlocked:
            step = cst.StepName.CONVERT
        self._current_step = step
        converting = step == cst.StepName.CONVERT
        self.workflow_pages.setCurrentIndex(0 if converting else 1)
        self.page_title.setText("1 · Convert your images" if converting else "2 · Process and analyse")
        self.back_button.setVisible(not converting)
        if not converting:
            phase = _STEP_PHASE[step]
            self.phase_tabs.blockSignals(True)
            self.phase_tabs.setCurrentIndex(phase - 1)
            self.phase_tabs.blockSignals(False)
            tabs = self._step_tabs[phase]
            tabs.blockSignals(True)
            tabs.setCurrentIndex(_PHASE_STEPS[phase][1].index(step))
            tabs.blockSignals(False)
        self._update_run_button_text()

    def _select_step(self, step: cst.StepName) -> None:
        """Navigate between step subtabs, retaining required-field warnings."""
        if not self._populating_settings and step != self._current_step:
            previous_phase = _STEP_PHASE[self._current_step]
            steps = (_PHASE_STEPS[previous_phase][1]
                     if _STEP_PHASE[step] != previous_phase else (self._current_step,))
            errors = [error for previous in steps
                      for error in self.adapter.missing_user_fields(previous)]
            if errors:
                QMessageBox.warning(self, "Missing required setting", "\n".join(errors))
                self._show_step(self._current_step)
                return
        self._show_step(step)

    def _substep_selected(self, phase: int, index: int) -> None:
        if not self._populating_settings and index >= 0:
            self._select_step(_PHASE_STEPS[phase][1][index])

    @Slot(int)
    def _phase_selected(self, index: int) -> None:
        if self._populating_settings or index < 0:
            return
        phase = index + 1
        selected = self._step_tabs[phase].currentIndex()
        self._select_step(_PHASE_STEPS[phase][1][max(0, selected)])

    @Slot()
    def _back_to_convert(self) -> None:
        if not self._running and self._thread is None:
            self._show_step(cst.StepName.CONVERT)

    def _refresh_phase_markers(self) -> None:
        for phase, (title, steps) in enumerate(_PHASE_STEPS[1:], start=1):
            active = any(self.adapter.step_enabled(step) for step in steps)
            self.phase_tabs.setTabText(phase - 1, title)
            self.phase_tabs.setTabToolTip(phase - 1,
                "At least one step is enabled." if active else "No steps are enabled.")
            for index, step in enumerate(steps):
                enabled = self.adapter.step_enabled(step)
                self._step_tabs[phase].setTabText(index, STEP_LAYOUTS[step].title)
                self._step_tabs[phase].setTabToolTip(index,
                    "Enabled" if enabled else "Use Enable in this subtab to include this step.")

    def _refresh_phase_access(self) -> None:
        root = Path(self.adapter.run_dir).expanduser() if self.adapter.run_dir else None
        prepared = False
        if root is not None and root.is_dir():
            try:
                prepared = next(root.rglob("fits_array.tif"), None) is not None
            except OSError:
                prepared = False
        self._prepared_available = prepared
        self._phases_unlocked = prepared or bool(self.adapter.runtime_value("unlock_all_tabs"))
        for step, editor in self._editors.items():
            editor.setEnabled(step == cst.StepName.CONVERT or self._phases_unlocked)
        self._refresh_phase_markers()
        if hasattr(self, "bgtune_button"):
            self.bgtune_button.setEnabled(prepared and not self._running)
        if hasattr(self, "segtune_button"):
            self.segtune_button.setEnabled(prepared and not self._running)
        for button in self._registration_tune_buttons.values():
            button.setEnabled(prepared and not self._running)
        self._refresh_tracking_viewer_button()
        self.channel_labels_button.setEnabled(
            not self._running and root is not None and root.is_dir())
        if not self._phases_unlocked and self._current_step != cst.StepName.CONVERT:
            self._show_step(cst.StepName.CONVERT)
        self._update_run_button_text()

    def _conversion_signature(self) -> dict:
        root = self.adapter.run_dir.strip()
        return {"run_dir": str(Path(root).expanduser().resolve()) if root else "",
                "params": deepcopy(self.adapter.as_mapping()["convert"]["params"])}

    def _conversion_is_current(self) -> bool:
        return self._prepared_available and self._converted_settings == self._conversion_signature()

    @Slot()
    def _primary_action(self) -> None:
        if self._current_step == cst.StepName.CONVERT:
            self._next_from_convert()
        else:
            self._run_pipeline()

    @Slot()
    def _next_from_convert(self) -> None:
        if self._running or self._thread is not None:
            return
        self._sync_identity()
        self._refresh_phase_access()
        if self._conversion_is_current():
            self._show_step(cst.StepName.REGISTER_TIME)
            return
        errors = self.adapter.validate_for_run((cst.StepName.CONVERT,))
        if errors:
            QMessageBox.warning(self, "Cannot convert images", "\n".join(errors))
            return
        if not self.adapter.step_enabled(cst.StepName.CONVERT):
            QMessageBox.warning(self, "Conversion required", "Enable Convert before continuing.")
            return
        self._launch_pipeline(convert_only=True)

    @Slot()
    def _browse_run_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self,
                                                    "Select FITS run directory",
                                                    self.run_dir_edit.text() or str(Path.home()),)
        if directory:
            self._switch_run_dir(directory)

    def _dropped_run_dir(self, mime_data: QMimeData) -> Path | None:
        if self._running:
            return None
        urls = mime_data.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        directory = Path(urls[0].toLocalFile())
        return directory if directory.is_dir() else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_run_dir(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._dropped_run_dir(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        directory = self._dropped_run_dir(event.mimeData())
        if directory is None:
            event.ignore()
            return
        self._switch_run_dir(str(directory))
        event.acceptProposedAction()

    @Slot()
    def _run_dir_entered(self) -> None:
        self._switch_run_dir(self.run_dir_edit.text())

    @Slot(str)
    def _run_dir_text_changed(self, value: str) -> None:
        if value.strip():
            self.channel_labels_button.setEnabled(
                not self._running and Path(value.strip()).expanduser().is_dir())
            return
        self.adapter.run_dir = ""
        self.run_browser.set_root("")
        self._refresh_report_button()
        self._refresh_phase_access()

    def _switch_run_dir(self, directory: str) -> None:
        self._begin_settings_population()
        raw_directory = directory.strip()
        if not raw_directory:
            self.run_dir_edit.clear()
            self.adapter.run_dir = ""
            self.run_browser.set_root("")
            self._refresh_report_button()
            self._refresh_phase_access()
            self._schedule_settings_population_finish()
            return

        resolved = Path(raw_directory).expanduser().resolve()
        # Each selected folder starts from the template, never the previous run.
        self.adapter = SettingsAdapter(template_path=self.adapter.template_path)
        self.adapter.run_dir = str(resolved)
        self._populate_from_adapter()

        saved_settings = run_settings_path(resolved)
        if saved_settings.is_file():
            self._load_settings_path(saved_settings, run_dir=resolved)
        else:
            self._append_log(f"Loaded template settings for {resolved}")

    def _sync_identity(self) -> None:
        self.adapter.run_dir = self.run_dir_edit.text().strip()
        self.adapter.user_name = self.user_name_edit.text().strip()
        self.run_browser.set_root(self.adapter.run_dir)
        if self.runtime_editor is not None:
            self.runtime_editor.sync_to_adapter()
        for editor in self._editors.values():
            editor.sync_to_adapter()

    @Slot()
    def _load_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self,
                                            "Load FITS settings",
                                            self.run_dir_edit.text() or str(Path.home()),
                                            "TOML settings (*.toml)",)
        if not path:
            return
        self._load_settings_path(Path(path))

    def _load_settings_path(self, path: Path, *, run_dir: Path | None = None) -> None:
        self._begin_settings_population()
        previous_document = self.adapter.document
        previous_source = self.adapter.source_path
        try:
            self.adapter.load(path)
            # A selected folder takes precedence over a copied settings file.
            if run_dir is not None:
                self.adapter.run_dir = str(run_dir)
            errors = self.adapter.validate_steps()
            if errors:
                first_step, error = next(iter(errors.items()))
                raise ValueError(f"{STEP_LAYOUTS[first_step].title}: {error}")
        except Exception as error:
            self.adapter.document = previous_document
            self.adapter.source_path = previous_source
            QMessageBox.critical(self, "Cannot load settings", str(error))
            self._schedule_settings_population_finish()
            return
        if run_dir is not None:
            self._conversion_root = None
        self._populate_from_adapter()
        self._append_log(f"Loaded settings from {path}")

    @Slot()
    def _save_settings(self) -> Path | None:
        self._sync_identity()
        if not self.adapter.run_dir:
            QMessageBox.warning(self, "Run directory required", "Select a run directory first.")
            return None
        step_errors = self.adapter.validate_steps()
        if step_errors:
            step, error = next(iter(step_errors.items()))
            QMessageBox.critical(self,
                                "Invalid settings",
                                f"{STEP_LAYOUTS[step].title}:\n{error}",)
            return None
        try:
            destination = self.adapter.save_to_run_dir()
        except OSError as error:
            QMessageBox.critical(self, "Cannot save settings", str(error))
            return None
        self._append_log(f"Saved settings to {destination}")
        return destination

    @Slot()
    def _run_pipeline(self) -> None:
        if self._running or self._thread is not None:
            return
        self._sync_identity()
        errors = self.adapter.validate_for_run()
        if not self._phases_unlocked:
            errors.append("Convert your images with Next before running the pipeline.")
        if errors:
            QMessageBox.warning(self, "Cannot run FITS", "\n".join(errors))
            return
        self._launch_pipeline(convert_only=False)

    def _launch_pipeline(self, *, convert_only: bool) -> None:
        label_window = self._channel_labels_window
        if (label_window is not None and label_window._job is not None
                and label_window._job.isRunning()):
            return
        self._sync_identity()
        settings_path = self._save_settings()
        if settings_path is None:
            return
        self._mask_expected_count = None
        self._conversion_run = convert_only
        self._advance_after_conversion = False
        self._pending_conversion = self._conversion_signature() if convert_only else None

        emitter = LogEmitter(self)
        emitter.message.connect(self._append_log)
        handler = QtLogHandler(emitter)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

        thread = QThread(self)
        worker = PipelineWorker(settings_path,
                                handler,
                                self.demo_step_delay,
                                convert_only=convert_only,
                                force_conversion=convert_only and self._prepared_available,)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.mask_requested.connect(self._enqueue_mask_request)
        worker.track_edit_requested.connect(self._enqueue_track_edit_request)
        worker.mask_expected_count.connect(self._set_mask_expected_count)
        worker.mask_input_complete.connect(self._mask_input_complete)
        worker.cancelled.connect(self._pipeline_cancelled)
        worker.cancelled.connect(thread.quit)
        worker.finished.connect(self._pipeline_finished)
        worker.failed.connect(self._pipeline_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)

        self._thread = thread
        self._worker = worker
        self._run_progress = worker.progress
        self._set_running(True)
        self._append_log("Starting FITS pipeline…")
        self._append_log("Settings edited while running apply to the next run.")
        thread.start()

    @Slot(object)
    def _enqueue_mask_request(self, request) -> None:
        from fits.gui.viewer.masks import MaskCollectionWindow
        if (self._worker is None
                or self._worker.interaction.mask_finished.is_set()
                or self._worker.interaction.cancelled.is_set()):
            return
        if self._mask_collection is None:
            window = MaskCollectionWindow(parent=self, preview=False, run_dir=Path(self.adapter.run_dir))
            interaction = self._worker.interaction
            window.experiment_finalized.connect(interaction.resolve_mask)
            window.collection_finished.connect(interaction.finish_mask_collection)
            window.cancellation_requested.connect(self._cancel_pipeline)
            self._mask_collection = window
            if self._mask_expected_count is not None:
                window.set_expected_experiments(self._mask_expected_count)
            window.show()
        self._mask_collection.enqueue_experiment(request)

    @Slot(int)
    def _set_mask_expected_count(self, count: int) -> None:
        self._mask_expected_count = count
        if self._mask_collection is not None:
            self._mask_collection.set_expected_experiments(count)

    @Slot(object)
    def _enqueue_track_edit_request(self, request: TrackEditRequest) -> None:
        if self._worker is None or self._worker.interaction.cancelled.is_set():
            return
        self._track_edit_queue.append(request)
        self._open_next_track_edit()

    def _open_next_track_edit(self) -> None:
        if self._tracking_editor is not None or not self._track_edit_queue:
            return
        from fits.gui.viewer.tracking import TrackingViewerWindow

        request = self._track_edit_queue.pop(0)
        window = TrackingViewerWindow(experiments_dir=self.adapter.run_dir,
                                        tracking_path=request.tracking_path,
                                        parent=self,
                                        editing_enabled=True,
                                        pipeline_request=request,)
        window.tracking_finalized.connect(self._tracking_edit_finalized)
        self._tracking_editor = window
        window.show()

    @Slot(object)
    def _tracking_edit_finalized(self, outcome: TrackEditOutcome) -> None:
        if self._worker is not None:
            self._worker.interaction.resolve_track_edit(outcome)
        self._tracking_editor = None
        QTimer.singleShot(0, self._open_next_track_edit)

    @Slot()
    def _cancel_pipeline(self) -> None:
        if self._worker is not None:
            self._worker.interaction.cancel()
            self.run_button.setText("Stopping…")
            self._append_log("Stopping pipeline. Any step already running must finish; no further work will start.")

    @Slot()
    def _mask_input_complete(self) -> None:
        if self._mask_collection is not None and not self._mask_collection._ended:
            self._mask_collection.no_more_requests()

    def _close_mask_collection(self) -> None:
        if self._mask_collection is not None:
            self._mask_collection._ended = True
            self._mask_collection.close()
            self._mask_collection.deleteLater()
            self._mask_collection = None

    def _close_tracking_editor(self) -> None:
        self._track_edit_queue.clear()
        if self._tracking_editor is not None:
            self._tracking_editor._pipeline_resolved = True
            self._tracking_editor.close()
            self._tracking_editor.deleteLater()
            self._tracking_editor = None

    @Slot()
    def _pipeline_cancelled(self) -> None:
        self._set_activity_active(False)
        self._close_mask_collection()
        self._close_tracking_editor()
        self._append_log("Pipeline cancelled. Completed work has been kept.")

    @Slot()
    def _pipeline_finished(self) -> None:
        self._set_activity_active(False)
        self._close_mask_collection()
        self._close_tracking_editor()
        had_errors = self._run_progress is not None and any(
            stage.status == StageStatus.FAILED or stage.error is not None
            for experiment in self._run_progress.snapshot()
            for stage in experiment.stages.values()
        )
        self._append_log("FITS pipeline completed with errors." if had_errors
                         else "FITS pipeline completed successfully.")
        self._refresh_phase_access()
        converted = self._run_progress is not None and any(
            experiment.stage(WorkflowStage.CONVERT) is not None
            and experiment.stages[WorkflowStage.CONVERT].status == StageStatus.COMPLETED
            for experiment in self._run_progress.snapshot())
        if self._conversion_run and converted and not had_errors and self._prepared_available:
            self._converted_settings = self._pending_conversion
            self._advance_after_conversion = True
        elif self._conversion_run:
            self._append_log("Conversion is incomplete. Review the log before continuing.")
        self._refresh_report_button()
        report = self._latest_report()
        if report is not None:
            if had_errors:
                self._show_report(report)
            else:
                self._append_log("The run report is available through Full Report.")

    @Slot(str, str)
    def _pipeline_failed(self, message: str, details: str) -> None:
        self._set_activity_active(False)
        self._close_mask_collection()
        self._close_tracking_editor()
        self._append_log(details)
        self._refresh_phase_access()
        self._refresh_report_button()
        report = self._latest_report()
        if report is not None and self._run_progress is not None and self._run_progress.snapshot():
            self._show_report(report)
            return
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("Pipeline stopped")
        dialog.setText("The FITS pipeline stopped because a task failed.")
        dialog.setInformativeText(message)
        dialog.setDetailedText(details)
        dialog.exec()

    @Slot()
    def _thread_finished(self) -> None:
        thread = self._thread
        if thread is not None:
            # finished can arrive before Qt's native worker cleanup is done.
            thread.wait()
        self._worker = None
        self._thread = None
        self._set_running(False)
        if self._advance_after_conversion and self._conversion_is_current():
            self._show_step(cst.StepName.REGISTER_TIME)
        self._advance_after_conversion = False
        self._conversion_run = False
        self._pending_conversion = None
        if thread is not None:
            thread.deleteLater()

    @Slot(str)
    def _append_log(self, message: str) -> None:
        self.console.appendPlainText(message)

    def _set_running(self, running: bool) -> None:
        self._running = running
        if self._channel_labels_window is not None:
            self._channel_labels_window.setEnabled(not running)
        if running:
            self.pipeline_progress.begin(self._run_progress)
        else:
            self.pipeline_progress.finish()
        self._set_activity_active(running)
        self.run_button.setEnabled(not running)
        self.load_button.setEnabled(not running)
        self.save_button.setEnabled(not running)
        self.browse_button.setEnabled(not running)
        self.run_dir_edit.setEnabled(not running)
        self.user_name_edit.setEnabled(not running)
        self.back_button.setEnabled(not running)
        if running:
            self.run_button.setText("Converting…" if self._conversion_run else "Running…")
        else:
            self._update_run_button_text()
        self._refresh_report_button()
        self._refresh_phase_access()

    def _set_activity_active(self, active: bool) -> None:
        if not active:
            self.pipeline_progress.finish()
        self.activity_indicator.setRange(0, 0 if active else 1)
        if not active:
            self.activity_indicator.setValue(0)
        self.activity_indicator.setVisible(active)

    def _update_run_button_text(self) -> None:
        if self._running or self._thread is not None:
            return
        converting = self._current_step == cst.StepName.CONVERT
        self.run_button.setText("Next" if converting else "Run pipeline")
        steps = (cst.StepName.CONVERT,) if converting else cst.WORKFLOW_ORDER
        missing = [error for step in steps for error in self.adapter.missing_user_fields(step)]
        if converting and not self.adapter.step_enabled(cst.StepName.CONVERT) and not self._conversion_is_current():
            missing.append("Enable Convert before continuing.")
        label_job = (self._channel_labels_window is not None
                     and self._channel_labels_window._job is not None
                     and self._channel_labels_window._job.isRunning())
        self.run_button.setEnabled(not missing and not label_job)
        action_help = (
            "Continue to processing. Reuse the converted images when conversion settings "
            "are unchanged; otherwise run Convert first."
            if converting else
            "Run the normal pipeline using all enabled steps and their overwrite settings.")
        self.run_button.setToolTip(
            action_help + ("\n\nBefore continuing:\n" + "\n".join(missing) if missing else ""))
        self.navigation_status.setText(
            ("Converted images are ready." if self._conversion_is_current()
             else "Next converts your images before processing.") if converting else "")

    def _latest_report(self) -> Path | None:
        if not self.adapter.run_dir:
            return None
        log_root = str(self.adapter.runtime_value("log_dir")).strip()
        root = Path(log_root).expanduser() if log_root else Path(self.adapter.run_dir)
        reports = sorted(reports_dir(root).glob("fits_report_*.txt"))
        return reports[-1] if reports else None

    def _refresh_report_button(self) -> None:
        self.report_button.setEnabled(
            not self._running and self._thread is None)

    def _tracking_artifacts(self, root: Path | None = None) -> list[Path]:
        if root is None:
            if not self.adapter.run_dir:
                return []
            root = Path(self.adapter.run_dir)
        if not root.is_dir():
            return []
        try:
            names = (cst.FITS_MASK_TRACK_EDITED_FILTERED,
                     cst.FITS_MASK_TRACK_EDITED,
                     cst.FITS_MASK_TRACK,)
            return [path for name in names for path in sorted(root.rglob(name))]
        except OSError:
            return []

    def _refresh_tracking_viewer_button(self) -> None:
        self.tracking_viewer_button.setEnabled(not self._running and self._thread is None)

    @Slot()
    def _open_channel_labels(self) -> None:
        run_dir = self.run_dir_edit.text().strip()
        if self._running or not run_dir or not Path(run_dir).expanduser().is_dir():
            return
        if Path(run_dir).expanduser().resolve() != Path(self.adapter.run_dir).expanduser().resolve():
            self._switch_run_dir(run_dir)
        from fits.gui.channel_labels import ChannelLabelsWindow

        window = self._channel_labels_window
        if window is not None and window.root != Path(self.adapter.run_dir).resolve():
            if window._job is not None and window._job.isRunning():
                window.showNormal()
                window.raise_()
                window.activateWindow()
                return
            window.close()
            window = None
        if window is not None and window.isVisible():
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.activateWindow()
            return
        window = ChannelLabelsWindow(self.adapter.run_dir)
        window.labels_saved.connect(self._channel_labels_saved)
        window.busy_changed.connect(self._update_run_button_text)
        self._channel_labels_window = window
        self._update_run_button_text()
        window.show()
        window.raise_()
        window.activateWindow()

    @Slot(object)
    def _channel_labels_saved(self, new_labels: dict[int, str]) -> None:
        from fits.channel_labels import rename_settings_document

        window = self._channel_labels_window
        old_labels = window.plan.labels if window is not None and window.plan is not None else ()
        mapping = {old: new_labels[index] for index, old in old_labels}
        self._sync_identity()
        rename_settings_document(self.adapter.document, mapping)
        self._populate_from_adapter()

    @Slot()
    def _open_tracking_viewer(self, path: Path | None = None) -> None:
        from fits.gui.viewer.tracking import TrackingViewerWindow

        if path is None and not self.adapter.run_dir.strip():
            QMessageBox.information(
                self, "Choose a run folder",
                "Choose your experiment or run folder first using Browse or drag and drop. "
                "Tracking Viewer can then look for saved tracking results.")
            return
        selected = path or self.run_browser.selected_path
        tracking_names = {cst.FITS_MASK_TRACK,
                          cst.FITS_MASK_TRACK_EDITED,
                          cst.FITS_MASK_TRACK_EDITED_FILTERED,}
        if (selected is None or selected.name not in tracking_names
                or not selected.is_file()):
            root = selected if selected is not None and selected.is_dir() else None
            artifacts = self._tracking_artifacts(root)
            selected = artifacts[0] if artifacts else None
        if selected is None:
            QMessageBox.information(
                self, "No tracking file found",
                "No tracking result was found in the selected experiment or run folder.\n\n"
                "First convert your images with Next if needed. Then enable Segmentation "
                "and Tracking under Process and click Run pipeline. If tracking results "
                "already exist, select the experiment folder containing them.")
            return
        viewer = self._tracking_viewer
        if viewer is not None and viewer.isVisible():
            if viewer._source_path == selected:
                if viewer.isMinimized():
                    viewer.showNormal()
                viewer.raise_()
                viewer.activateWindow()
                return
            viewer.close()
        self._tracking_viewer = TrackingViewerWindow(
            experiments_dir=self.adapter.run_dir, tracking_path=selected,
            editing_enabled=False, selection_enabled=True)
        self._tracking_viewer.show()
        self._tracking_viewer.raise_()
        self._tracking_viewer.activateWindow()

    @Slot()
    def _open_latest_report(self) -> None:
        report = self._latest_report()
        if report is not None:
            self._show_report(report)
        elif not self.adapter.run_dir.strip():
            QMessageBox.information(
                self, "Choose a run folder",
                "Choose your experiment or run folder first using Browse or drag and drop. "
                "Full Report opens the latest saved report for that run.")
        else:
            QMessageBox.information(
                self, "No report found",
                "No saved report was found for this run.\n\n"
                "Click Next on the Convert page to convert your images, or Run pipeline "
                "on the processing page. A report is saved when the run finishes.")

    @Slot(object)
    def _open_selected_report(self, path: object) -> None:
        if not isinstance(path, (str, Path)):
            return
        report = Path(path)
        if report.is_file() and report.name in {cst.FITS_MASK_TRACK,
                                                cst.FITS_MASK_TRACK_EDITED,
                                                cst.FITS_MASK_TRACK_EDITED_FILTERED}:
            self._open_tracking_viewer(report)
            return
        if report.is_file() and report.name.startswith("fits_report_") and report.suffix == ".txt":
            self._show_report(report)

    def _show_report(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "Cannot open report", str(error))
            return
        ReportDialog(path, content, self).exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(self,
                                    "Pipeline is running",
                                    "Wait for the pipeline to finish before closing FITS.",)
            event.ignore()
            return
        label_window = self._channel_labels_window
        if (label_window is not None and label_window._job is not None
                and label_window._job.isRunning()):
            event.ignore()
            return
        if self._tracking_viewer is not None:
            self._tracking_viewer.close()
        if self._channel_labels_window is not None:
            self._channel_labels_window.close()
        super().closeEvent(event)
