from __future__ import annotations
from fits.settings.models import ExtractSettings
from fits.gui.theme import STEP_TAB_BAR_STYLE

from fits.workflows.checks.models import PreflightReport, RawInputReport
from fits.workflows.checks.raw_inputs import inspect_raw_inputs
from fits.workflows.file_management.rebuild import ProcessingPlan
from fits.workflows.runtime.interactive.messages import MaskCollectionRequest, TrackEditRequest, TrackEditOutcome
import logging
import psutil
from copy import deepcopy
from pathlib import Path
from fits.environment.paths import is_internal_path, reports_dir
from PySide6.QtCore import QEventLoop, QMimeData, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent, QShowEvent
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget
from fits.environment import constant as cst
from fits.workflows.artifacts.paths import first_image
from fits.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage
from fits.gui.settings import STEP_LAYOUTS, RuntimeSettingsEditor, SettingsAdapter, StepSettingsEditor
from fits.gui.run_result.report import ReportDialog
from fits.gui.run_result.dialog import show_run_result
from fits.gui.file_management.manager import manage_files
from fits.workflows.runtime.progress.outcome import RunResult, summarize_run
from fits.workflows.checks.space import file_bytes
from fits.gui.main_window.run_browser import COMPATIBLE_COLOR, OUTDATED_COLOR, RunDirectoryBrowser
from fits.gui.main_window.logging import LogEmitter, QtLogHandler
from fits.gui.main_window.pipeline_worker import PipelineWorker
from fits.gui.main_window.emergency_stop import terminate_application
from fits.gui.main_window.progress_display import PipelineProgressWidget
from fits.settings.models import BGSubSettings, RegisterChannelSettings, RegisterTimeSettings, SegmentSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.settings.loader import run_settings_path
from fits.workflows.experiments.roots import resolve_run_root
from fits.gui.artifact_decisions import choose_artifacts
from fits.workflows.checks.compatibility import inspect_run_compatibility
from fits_io import FitsIO
from fits.workflows.file_management.history import snapshots
from fits.gui.dialogs import size_resizable_dialog
from fits.gui.theme import PREVIEW_BUTTON_STYLE
from fits.gui.parquet import open_parquet
from fits.gui.segmentation_models.loader import model_options_loader
from fits.gui.segmentation_models.options import CellposeModelOptions
from fits.workflows.runtime.errors import PipelineCancelled
from fits.channel_labels import rename_settings_document
from fits.workflows.file_management.rebuild import execution_config
from fits.workflows.runtime.scheduler.planning import resolve_runtime_steps
from fits.workflows.checks.artifacts import inspect_run


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
        """
        Initialize the FitsMainWindow state and dependencies.
        """
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
        self._upgrading = False
        self._maintenance_plan: ProcessingPlan | None = None
        self._run_error = ""
        self._run_cancelled = False
        self._run_size_bytes = 0
        self._run_status = None
        self._artifact_report = None
        self._file_channel_cache = {}
        self._raw_input_report: RawInputReport | None = None
        self._current_step = cst.StepName.CONVERT
        self._conversion_root: str | None = None
        self._converted_settings: dict | None = None
        self._pending_conversion: dict | None = None
        self._advance_after_conversion = False
        self._conversion_run = False
        self._last_run_succeeded = False
        self._next_artifact_decision = None
        self._editors: dict[cst.StepName, StepSettingsEditor] = {}
        self.runtime_editor: RuntimeSettingsEditor | None = None
        self._segmentation_tuner = None
        self._segmentation_preview_pending = False
        self._background_tuner = None
        self._registration_tuner = None
        self._registration_tune_buttons: dict[cst.StepName, QPushButton] = {}
        self._tracking_viewer = None
        self._channel_labels_window = None
        self._prepared_available = False
        self._phases_unlocked = False
        self._populating_settings = False
        self._settings_population_generation = 0
        self._startup_height_applied = False

        self.setWindowTitle("FITS")
        self.setAcceptDrops(True)
        self.resize(1200, 850)
        self._build_ui()
        self._populate_from_adapter()
        loader = model_options_loader()
        loader.ready.connect(self._segmentation_models_ready)
        loader.failed.connect(self._segmentation_models_failed)

    def showEvent(self, event: QShowEvent) -> None:
        """
        Fit the initial window height after its native frame becomes available.
        """
        super().showEvent(event)
        if not self._startup_height_applied:
            self._startup_height_applied = True
            QTimer.singleShot(0, self._fit_startup_height)

    def _fit_startup_height(self) -> None:
        """
        Fill the current screen's usable height while preserving window width.
        """
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame_height = self.frameGeometry().height() - self.height()
        self.resize(self.width(), max(1, available.height() - frame_height))
        self.move(self.pos().x(), available.top())

    def _build_ui(self) -> None:
        """
        Build ui.
        """
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
        self.tracking_viewer_button = QPushButton("Image / Mask Viewer")
        self.tracking_viewer_button.setToolTip(
            "Inspect intermediate, compacted or earlier FITS images and masks, including REF/ROI. "
            "Tracking results also offer trajectories and track-length filtering.")
        self.tracking_viewer_button.setStyleSheet(
            "QPushButton { background-color: #d97706; color: white; font-weight: bold; } "
            "QPushButton:disabled { background-color: #6b4b2a; color: #aaa; }")
        self.tracking_viewer_button.clicked.connect(lambda: self._open_tracking_viewer())
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
        browser_panels = QWidget()
        browser_layout = QVBoxLayout(browser_panels)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        summary_panel = QFrame()
        summary_panel.setObjectName("experimentStatusPanel")
        summary_panel.setStyleSheet("#experimentStatusPanel { border: 1px solid #56616f; border-radius: 8px; }")
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.setContentsMargins(10, 10, 10, 10)
        summary_row = QHBoxLayout()
        self.file_status_label = QLabel('Experiment files')
        self.file_status_label.setWordWrap(True)
        summary_row.addWidget(self.file_status_label, 1)
        self.file_details_button = QPushButton('Details…')
        self.file_details_button.setToolTip('Explain file compatibility, read-only viewing and upgrade options for this run.')
        self.file_details_button.clicked.connect(self._show_file_details)
        summary_row.addWidget(self.file_details_button)
        self.manage_files_button = QPushButton('Manage files…')
        self.manage_files_button.setToolTip('Migrate older results, update run paths/tags, rebuild outdated results, compact experiments, or restore/delete retained backups.')
        self.manage_files_button.clicked.connect(self._manage_files)
        summary_row.addWidget(self.manage_files_button)
        summary_layout.addLayout(summary_row)
        metadata_row = QHBoxLayout()
        self.file_channels_label = QLabel('Channels: —')
        self.file_channels_label.setWordWrap(True)
        self.file_channels_label.setTextFormat(Qt.TextFormat.PlainText)
        metadata_row.addWidget(self.file_channels_label, 1)
        self.file_size_label = QLabel("Run size: —")
        self.file_size_label.setToolTip("Total size of the run directory, including original acquisitions, results, caches and retained backups.")
        metadata_row.addWidget(self.file_size_label)
        summary_layout.addLayout(metadata_row)
        browser_layout.addWidget(summary_panel)
        browser_layout.addWidget(self.run_browser, 1)
        self.run_browser.path_selected.connect(self._selection_status_changed)
        top_splitter.addWidget(browser_panels)
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
            tabs.tabBar().setStyleSheet(STEP_TAB_BAR_STYLE)
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
        self.run_button.setStyleSheet(
            "QPushButton { background-color: #16803b; color: white; "
            "font-weight: bold; padding: 7px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #1c9848; } "
            "QPushButton:pressed { background-color: #11652f; } "
            "QPushButton:disabled { background-color: #72987c; color: #e0e0e0; }")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setStyleSheet(
            "QPushButton { background-color: #b32632; color: white; border: 1px solid #dc4652; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #cf3040; }"
            "QPushButton:pressed { background-color: #8d1d27; }")
        self.stop_button.setToolTip("Immediately stop all processing and exit FITS after confirmation.")
        self.stop_button.clicked.connect(self._confirm_emergency_stop)
        self.load_button.clicked.connect(self._load_settings)
        self.save_button.clicked.connect(self._save_settings)
        self.run_button.clicked.connect(self._primary_action)
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch()
        self.navigation_status = QLabel()
        self.navigation_status.setWordWrap(True)
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
        buttons.addWidget(self.stop_button)
        outer.addLayout(buttons)

        self.setCentralWidget(central)

    def _populate_from_adapter(self) -> None:
        """
        Populate from adapter.
        """
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
                tune_button.setStyleSheet(PREVIEW_BUTTON_STYLE)
                tune_button.setToolTip(f"Preview {operation}. Requires a converted fits_array.tif image.")
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
                self.bgtune_button.setStyleSheet(PREVIEW_BUTTON_STYLE)
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
                tune_layout.addWidget(self.bgtune_button, 0, Qt.AlignmentFlag.AlignVCenter)
                editor.outer_layout.insertWidget(1, tune_row)
            if step == cst.StepName.SEGMENT:
                tune_row = QWidget()
                tune_layout = QHBoxLayout(tune_row)
                tune_layout.setContentsMargins(0, 0, 0, 0)
                tune_layout.setSpacing(16)
                self.segtune_button = QPushButton('Loading models…' if self._segmentation_preview_pending else 'Preview')
                self.segtune_button.setStyleSheet(PREVIEW_BUTTON_STYLE)
                self.segtune_button.setToolTip(
                    "Preview segmentation and adjust Cellpose settings. "
                    "Requires a converted fits_array.tif image in the run directory.")
                self.segtune_button.clicked.connect(lambda: self._open_segmentation_tuner("segmentation"))
                tune_description = QLabel(
                    "Preview segmentation on an image and adjust Cellpose settings. "
                    "Save current settings copies all channel settings back here.")
                tune_description.setWordWrap(True)
                tune_description.setToolTip(tune_description.text())
                tune_description.setStyleSheet("color: #b8b8b8;")
                tune_layout.addWidget(tune_description, 1)
                tune_layout.addWidget(self.segtune_button, 0, Qt.AlignmentFlag.AlignVCenter)
                editor.outer_layout.insertWidget(1, tune_row)
            if step == cst.StepName.EXTRACT:
                editor.compartment_preview_button.setStyleSheet(PREVIEW_BUTTON_STYLE)
                editor.compartment_preview_button.clicked.connect(lambda: self._open_segmentation_tuner("compartment"))
            editor.set_editable(self.adapter.step_enabled(step))
            tabs = self.convert_tabs if step == cst.StepName.CONVERT else self._step_tabs[_STEP_PHASE[step]]
            tabs.addTab(editor, STEP_LAYOUTS[step].title)
            self._editors[step] = editor

        for step in (cst.StepName.CONVERT, cst.StepName.SEGMENT):
            self._editors[step].value_changed.connect(self._refresh_channel_choices)

        self._refresh_run_inventory()
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

    @Slot()
    def _refresh_channel_choices(self) -> None:
        """
        Propagate export and segmentation selections through dependent GUI controls.
        """
        for editor in self._editors.values():
            editor.refresh_channel_choices()
        self._update_run_button_text()

    def _begin_settings_population(self) -> None:
        """
        Begin settings population.
        """
        self._settings_population_generation += 1
        self._populating_settings = True

    def _schedule_settings_population_finish(self) -> None:
        """
        Schedule settings population finish.
        """
        generation = self._settings_population_generation
        QTimer.singleShot(0, lambda: self._finish_populating_settings(generation))

    def _finish_populating_settings(self, generation: int) -> None:
        """
        Finish populating settings.
        """
        if generation == self._settings_population_generation:
            self._populating_settings = False

    @Slot()
    def _open_background_tuner(self) -> None:
        """
        Open background tuning with GUI settings and a fixed run directory.
        """
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
        tuner = BackgroundTunerWindow(self.adapter.run_dir or None,
                                      settings=settings,
                                      directory_locked=True,
                                      initial_path=self.run_browser.selected_path,
                                      parent=self,
                                      )
        tuner.setWindowModality(Qt.WindowModality.WindowModal)
        tuner.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tuner.settings_applied.connect(self._apply_background_settings)
        tuner.destroyed.connect(lambda: setattr(self, "_background_tuner", None))
        self._background_tuner = tuner
        tuner.show()

    def _tuner_expanded_sections(self,
                                 step: cst.StepName,
                                 settings: BGSubSettings | RegisterTimeSettings | RegisterChannelSettings,
                                 ) -> set[cst.StepName]:
        """
        Preserve open sections and reveal only changed advanced tuner values.
        """
        expanded = {name for name, editor in self._editors.items() if editor.advanced_settings_visible}
        current = type(settings).model_validate(self.adapter.as_mapping()[step]["params"])
        before, after = current.to_payload_dict(), settings.to_payload_dict()
        advanced = set(STEP_LAYOUTS[step].advanced)
        if isinstance(settings, (RegisterTimeSettings, RegisterChannelSettings)):
            assert isinstance(current, (RegisterTimeSettings, RegisterChannelSettings))
            previous = resolve_registration_plan(current.context, current.algorithm, current.method)
            effective = resolve_registration_plan(settings.context, settings.algorithm, settings.method)
            preset = resolve_registration_plan(settings.context)
            for field in ("algorithm", "method"):
                before[field] = getattr(previous, field)
                after[field] = getattr(effective, field)
            if effective == preset:
                advanced.difference_update(("algorithm", "method"))
        if any(before.get(field) != after[field] for field in advanced if field in after):
            expanded.add(step)
        return expanded

    @Slot(object)
    def _apply_background_settings(self, settings: BGSubSettings) -> None:
        """
        Transfer tuning parameters while preserving step-enabled and runtime states.
        """
        expanded = self._tuner_expanded_sections(cst.StepName.BG_SUB, settings)
        for key, value in {**settings.to_payload_dict(), "overwrite": settings.overwrite}.items():
            self.adapter.set_field_value(cst.StepName.BG_SUB, key, "None" if value is None else value)
        self._populate_from_adapter()
        for name in expanded:
            self._editors[name].show_advanced_settings()
        self._show_step(cst.StepName.BG_SUB)
        self._append_log("Applied background-subtraction settings from the tuner.")

    @Slot()
    def _open_segmentation_tuner(self, initial_tab: str | None = None) -> None:
        """
        Open Preview after the shared background discovery has completed.
        """
        self._pending_tuner_tab = initial_tab or getattr(self, "_pending_tuner_tab", "segmentation")
        loader = model_options_loader()
        if loader.options is None:
            if loader.error:
                QMessageBox.warning(self, 'Cannot load Cellpose models', loader.error)
                return
            self._segmentation_preview_pending = True
            self.segtune_button.setText('Loading models…')
            self.segtune_button.setToolTip('Cellpose is loading in the background. Preview will open when it is ready.')
            loader.start()
            return

        from fits.gui.viewer.segmentation import SegmentationTunerWindow

        self._sync_identity()
        self._editors[cst.StepName.SEGMENT].sync_to_adapter()
        self._editors[cst.StepName.EXTRACT].sync_to_adapter()
        try:
            settings = self.adapter.segmentation_settings(for_tuning=True)
        except ValueError as error:
            QMessageBox.critical(self, "Cannot open segmentation tuner", str(error))
            return
        tuner = SegmentationTunerWindow(experiments_dir=self.adapter.run_dir or None,
                                        segment_settings=settings,
                                        extract_settings=ExtractSettings.model_validate(self.adapter.as_mapping()[cst.StepName.EXTRACT]["params"]),
                                        initial_tab=self._pending_tuner_tab,
                                        parent=self,
                                        initial_path=self.run_browser.selected_path,
                                        directory_locked=True,
                                        )
        tuner.setWindowModality(Qt.WindowModality.WindowModal)
        tuner.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tuner.settings_applied.connect(self._apply_segmentation_settings)
        tuner.compartment_settings_applied.connect(self._apply_compartment_settings)
        tuner.channel_removed.connect(self._remove_tuner_channel)
        tuner.destroyed.connect(lambda: setattr(self, "_segmentation_tuner", None))
        self._segmentation_tuner = tuner
        tuner.show()

    def _segmentation_models_ready(self, _options: CellposeModelOptions) -> None:
        """
        Continue an early Preview request using the completed shared discovery.
        """
        if self._segmentation_preview_pending:
            self._clear_segmentation_preview_request()
            self._open_segmentation_tuner()

    def _segmentation_models_failed(self, error: str) -> None:
        """
        Explain a failed pending Preview without preventing other GUI work.
        """
        if self._segmentation_preview_pending:
            self._clear_segmentation_preview_request()
            QMessageBox.warning(self, 'Cannot load Cellpose models', error)

    def _clear_segmentation_preview_request(self) -> None:
        """
        Reset a queued Preview when it opens or the user starts other work or closes FITS.
        """
        self._segmentation_preview_pending = False
        self.segtune_button.setText('Preview')
        self.segtune_button.setToolTip('Preview segmentation and adjust Cellpose settings.')

    def _open_registration_tuner(self, mode: str) -> None:
        """
        Open registration tuner.
        """
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
        tuner = RegistrationTunerWindow(self.adapter.run_dir or None,
                                        mode="time" if mode == "time" else "channel",
                                        time_settings=time_settings,
                                        channel_settings=channel_settings,
                                        initial_path=self.run_browser.selected_path,
                                        parent=self,
                                        directory_locked=True,
                                        )
        tuner.setWindowModality(Qt.WindowModality.WindowModal)
        tuner.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tuner.settings_applied.connect(self._apply_registration_settings)
        tuner.destroyed.connect(lambda: setattr(self, "_registration_tuner", None))
        self._registration_tuner = tuner
        tuner.show()

    @Slot(str, object)
    def _apply_registration_settings(self,
                                     mode: str,
                                     settings: RegisterTimeSettings | RegisterChannelSettings,
                                     ) -> None:
        """
        Apply registration settings, revealing changed manual overrides only.
        """
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
        """
        Apply channel parameters without changing advanced-section visibility.
        """
        expanded = {name for name, editor in self._editors.items() if editor.advanced_settings_visible}
        self.adapter.set_segment_channels([entry.to_payload_dict() for entry in settings.channels])
        self._populate_from_adapter()
        for name in expanded:
            self._editors[name].show_advanced_settings()
        self._show_step(cst.StepName.SEGMENT)
        self._append_log("Applied settings from the segmentation tuner.")

    def _apply_compartment_settings(self, settings: ExtractSettings) -> None:
        """
        Copy only compartment options into Quantification, preserving other settings.
        """
        expanded = {name for name, editor in self._editors.items() if editor.advanced_settings_visible}
        for name in ("compartments", "membrane_thickness", "dilation_radius", "save_compartment_masks"):
            self.adapter.set_field_value(cst.StepName.EXTRACT, name, getattr(settings, name))
        self._populate_from_adapter()
        for name in expanded:
            self._editors[name].show_advanced_settings()
        self._show_step(cst.StepName.EXTRACT)
        self._append_log("Saved compartment settings to Quantification.")

    def _remove_tuner_channel(self, channel: str) -> None:
        """
        Remove one saved segmentation entry without applying other tuner edits.
        """
        expanded = {name for name, editor in self._editors.items() if editor.advanced_settings_visible}
        self.adapter.set_segment_channels([entry for entry in self.adapter.segment_channels()
                                           if entry["channel"] != channel])
        self._populate_from_adapter()
        for name in expanded:
            self._editors[name].show_advanced_settings()

    def _show_step(self, step: cst.StepName) -> None:
        """
        Display one step without triggering navigation validation.
        """
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
        """
        Navigate between step subtabs, retaining required-field warnings.
        """
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
        """
        Substep selected.
        """
        if not self._populating_settings and index >= 0:
            self._select_step(_PHASE_STEPS[phase][1][index])

    @Slot(int)
    def _phase_selected(self, index: int) -> None:
        """
        Phase selected.
        """
        if self._populating_settings or index < 0:
            return
        phase = index + 1
        selected = self._step_tabs[phase].currentIndex()
        self._select_step(_PHASE_STEPS[phase][1][max(0, selected)])

    @Slot()
    def _back_to_convert(self) -> None:
        """
        Back to convert.
        """
        if not self._running and self._thread is None:
            self._show_step(cst.StepName.CONVERT)

    def _refresh_phase_markers(self) -> None:
        """
        Refresh phase markers.
        """
        for phase, (title, steps) in enumerate(_PHASE_STEPS[1:], start=1):
            active = any(self.adapter.step_enabled(step) for step in steps)
            self.phase_tabs.setTabText(phase - 1, title)
            self.phase_tabs.setTabToolTip(phase - 1,
                                          "At least one step is enabled." if active else "No steps are enabled.",
                                          )
            for index, step in enumerate(steps):
                enabled = self.adapter.step_enabled(step)
                self._step_tabs[phase].setTabText(index, STEP_LAYOUTS[step].title)
                self._step_tabs[phase].setTabToolTip(index,
                                                     "Enabled" if enabled else "Use Enable in this subtab to include this step.",
                                                     )

    def _refresh_phase_access(self) -> None:
        """
        Refresh phase access.
        """
        root = Path(self.adapter.run_dir).expanduser() if self.adapter.run_dir else None
        prepared = False
        if root is not None and root.is_dir():
            try:
                prepared = first_image(root) is not None
            except OSError:
                prepared = False
        self._prepared_available = prepared
        read_only = self._run_status is not None and self._run_status.outdated and not self._upgrading
        self._phases_unlocked = prepared or read_only or bool(self.adapter.runtime_value("unlock_all_tabs"))
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
        self.channel_labels_button.setEnabled(not self._running and root is not None and root.is_dir())
        if not self._phases_unlocked and self._current_step != cst.StepName.CONVERT:
            self._show_step(cst.StepName.CONVERT)
        self._update_run_button_text()
        outdated = self._run_status is not None and self._run_status.outdated
        self.channel_labels_button.setEnabled(not self._running and not outdated and root is not None and root.is_dir())
        self.manage_files_button.setEnabled(not self._running and root is not None and root.is_dir())
        if outdated and not self._upgrading:
            for button in (*self._registration_tune_buttons.values(), getattr(self, 'bgtune_button', None), getattr(self,
                                                                                                                    'segtune_button',
                                                                                                                    None,
                                                                                                                    )):
                if button is not None:
                    button.setEnabled(False)

    def _conversion_signature(self) -> dict:
        """
        Conversion signature.
        """
        root = self.adapter.run_dir.strip()
        return {"run_dir": str(Path(root).expanduser().resolve()) if root else "",
                "params": deepcopy(self.adapter.as_mapping()["convert"]["params"])}

    def _conversion_is_current(self) -> bool:
        """
        Conversion is current.
        """
        return self._prepared_available and self._converted_settings == self._conversion_signature()

    @Slot()
    def _primary_action(self) -> None:
        """
        Primary action.
        """
        if self._current_step == cst.StepName.CONVERT:
            self._next_from_convert()
        else:
            self._run_pipeline()

    @Slot()
    def _next_from_convert(self) -> None:
        """
        Next from convert.
        """
        if self._run_status is not None and self._run_status.outdated and not self._upgrading:
            self._show_step(cst.StepName.REGISTER_TIME)
            return
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
        """
        Browse run dir.
        """
        directory = QFileDialog.getExistingDirectory(self,
                                                     "Select FITS run directory",
                                                     self.run_dir_edit.text() or str(Path.home()),
                                                     )
        if directory:
            self._switch_run_dir(directory)

    def _dropped_run_dir(self, mime_data: QMimeData) -> Path | None:
        """
        Dropped run dir.
        """
        if self._running:
            return None
        urls = mime_data.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        directory = Path(urls[0].toLocalFile())
        return directory if directory.is_dir() else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """
        Accept a supported directory drag when the GUI is idle.
        """
        if self._dropped_run_dir(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """
        Update acceptance of the dragged run directory.
        """
        if self._dropped_run_dir(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """
        Open the dropped directory through the normal run-loading flow.
        """
        directory = self._dropped_run_dir(event.mimeData())
        if directory is None:
            event.ignore()
            return
        self._switch_run_dir(str(directory))
        event.acceptProposedAction()

    @Slot()
    def _run_dir_entered(self) -> None:
        """
        Run dir entered.
        """
        self._switch_run_dir(self.run_dir_edit.text())

    @Slot(str)
    def _run_dir_text_changed(self, value: str) -> None:
        """
        Run dir text changed.
        """
        if value.strip():
            self.channel_labels_button.setEnabled(not self._running and Path(value.strip()).expanduser().is_dir(),
                                                  )
            return
        self.adapter.run_dir = ""
        self.run_browser.set_root("")
        self._refresh_report_button()
        self._refresh_phase_access()

    def _switch_run_dir(self, directory: str) -> None:
        """
        Switch run dir.
        """
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

        selected = Path(raw_directory).expanduser().resolve()
        try:
            resolved = resolve_run_root(selected)
        except ValueError as error:
            QMessageBox.warning(self, 'Choose the containing run', str(error))
            self._schedule_settings_population_finish()
            return
        # Each selected folder starts from the template, never the previous run.
        self.adapter = SettingsAdapter(template_path=self.adapter.template_path)
        self.adapter.run_dir = str(resolved)
        self._populate_from_adapter()

        saved_settings = run_settings_path(resolved)
        if saved_settings.is_file():
            self._load_settings_path(saved_settings, run_dir=resolved)
        else:
            self._append_log(f"Loaded template settings for {resolved}")
        if selected != resolved:
            self.run_browser.select_path(selected)
            self._append_log(f"Opened containing run {resolved}; selected {selected.name}.")

    def _sync_identity(self) -> None:
        """
        Sync identity.
        """
        self.adapter.run_dir = self.run_dir_edit.text().strip()
        self.adapter.user_name = self.user_name_edit.text().strip()
        self.run_browser.set_root(self.adapter.run_dir)
        if self.runtime_editor is not None:
            self.runtime_editor.sync_to_adapter()
        for editor in self._editors.values():
            editor.sync_to_adapter()

    @Slot()
    def _load_settings(self) -> None:
        """
        Load settings.
        """
        path, _ = QFileDialog.getOpenFileName(self,
                                              "Load FITS settings",
                                              self.run_dir_edit.text() or str(Path.home()),
                                              "TOML settings (*.toml)",
                                              )
        if not path:
            return
        self._load_settings_path(Path(path))

    def _load_settings_path(self, path: Path, *, run_dir: Path | None = None) -> None:
        """
        Load settings path.
        """
        self._begin_settings_population()
        previous_document = self.adapter.document
        previous_source = self.adapter.source_path
        try:
            self.adapter.load(path)
            if run_dir is None and path.parent.name == '.fits':
                run_dir = path.parent.parent.resolve()
            elif run_dir is None and self.run_dir_edit.text().strip():
                run_dir = Path(self.run_dir_edit.text()).expanduser().resolve()
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
        """
        Save settings.
        """
        self._sync_identity()
        if not self.adapter.run_dir:
            QMessageBox.warning(self, "Run directory required", "Select a run directory first.")
            return None
        step_errors = self.adapter.validate_steps()
        if step_errors:
            step, error = next(iter(step_errors.items()))
            QMessageBox.critical(self, "Invalid settings", f"{STEP_LAYOUTS[step].title}:\n{error}")
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
        """
        Run pipeline.
        """
        if self._run_status is not None and self._run_status.outdated and not self._upgrading:
            QMessageBox.information(self,
                                    'Run is read-only',
                                    'Use Manage files to migrate this run before processing.',
                                    )
            return
        if self._running or self._thread is not None:
            return
        self._sync_identity()
        if self._maintenance_plan is None:
            errors = self.adapter.validate_for_run()
        else:
            selected = tuple({cst.StepName(step) for steps in self._maintenance_plan.scope.values() for step in steps})
            errors = self.adapter.validate_for_run(selected)
            try:
                resolve_runtime_steps(execution_config(self.adapter.as_mapping(), self._maintenance_plan))
            except ValueError as error:
                errors.append(str(error))
        if not self._phases_unlocked and not self._upgrading:
            errors.append("Convert your images with Next before running the pipeline.")
        if errors:
            QMessageBox.warning(self, "Cannot run FITS", "\n".join(errors))
            return
        self._launch_pipeline(convert_only=False)

    def _launch_pipeline(self, *, convert_only: bool) -> None:
        """
        Launch pipeline.
        """
        if convert_only or self.adapter.step_enabled(cst.StepName.CONVERT):
            root = Path(self.adapter.run_dir).expanduser() if self.adapter.run_dir else None
            self._refresh_raw_inputs(root)
            input_error = self._raw_input_error()
            if input_error:
                self._update_run_button_text()
                QMessageBox.warning(self, "Cannot convert images", input_error)
                return
        label_window = self._channel_labels_window
        if (label_window is not None and label_window._job is not None
                and label_window._job.isRunning()):
            return
        self._sync_identity()
        settings_path = self._save_settings()
        if settings_path is None:
            return
        self._mask_expected_count = None
        self._last_run_succeeded = False
        self._run_error = ""
        self._run_cancelled = False
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
                                force_conversion=convert_only and self._prepared_available,
                                upgrading=self._upgrading,
                                )
        worker.maintenance = self._maintenance_plan
        worker.moveToThread(thread)
        worker.artifact_decision_requested.connect(self._artifact_decision_requested)
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
    def _artifact_decision_requested(self, report: PreflightReport) -> None:
        """
        Artifact decision requested.
        """
        worker = self._worker
        if worker is not None:
            decision = self._next_artifact_decision or choose_artifacts(report, self)
            self._next_artifact_decision = None
            worker.interaction.decisions.put(decision)

    def _refresh_run_inventory(self) -> None:
        """
        Refresh run inventory.
        """
        root = Path(self.adapter.run_dir).expanduser() if self.adapter.run_dir else None
        self._run_status = inspect_run_compatibility(root) if root is not None and root.is_dir() else None
        self._artifact_report = None
        self._run_size_bytes = file_bytes(root.rglob("*")) if root is not None and root.is_dir() else 0
        if self._run_status is not None and not self._run_status.outdated:
            self._artifact_report = inspect_run(self._run_status.root,
                                                self.adapter.as_mapping(),
                                                for_execution=False,
                                                )
        self._file_channel_cache.clear()
        self._refresh_raw_inputs(root)
        conflicts = {record.path.parent for record in self._artifact_report.conflicts} if self._artifact_report is not None else set()
        self.run_browser.set_experiment_status(self._run_status, conflicts)
        self._selection_status_changed(self.run_browser.selected_path)

    def _refresh_raw_inputs(self, root: Path | None) -> None:
        """
        Reuse shared raw-input checks for channel hints and blocking run problems.
        """
        self._raw_input_report = inspect_raw_inputs(root) if root is not None and root.is_dir() else None
        counts = set(self._raw_input_report.channel_counts.values()) if self._raw_input_report is not None else set()
        if self._raw_input_report is not None and self._raw_input_report.problems and len(counts) <= 1:
            counts.clear()
        self._editors[cst.StepName.CONVERT].set_expected_channel_counts(counts)

    def _raw_input_error(self) -> str:
        """
        Return the shared raw-input report's actionable error description.
        """
        return self._raw_input_report.describe() if self._raw_input_report is not None else ""

    @Slot(object)
    def _selection_status_changed(self, selected: Path | None = None) -> None:
        """
        Selection status changed.
        """
        status = self._run_status
        if status is None:
            self.adapter.saved_image_channels = []
            self._refresh_channel_choices()
            self.file_status_label.setText('Experiment files')
            self.file_status_label.setStyleSheet('')
            self.file_size_label.setText('Run size: —')
            self.file_channels_label.setText('Channels: —')
            self.file_details_button.setEnabled(False)
            return
        self.file_details_button.setEnabled(True)
        scope = Path(selected) if selected is not None else status.root
        if scope.is_file():
            scope = scope.parent
        files = [path for path in status.files if path.parent == scope or scope in path.parents]
        conflicts = self._artifact_report is not None and bool(self._artifact_report.conflicts)
        input_error = self._raw_input_error()
        self.file_status_label.setText('Raw inputs need attention — cannot convert' if input_error else
                                       'Upgrade to FITS v4 required - read-only' if status.outdated else
                                       'Outdated downstream results' if conflicts else
                                       ('Current — editable' if status.states else 'Fresh inputs — conversion available'))
        color = '#e57373' if input_error else OUTDATED_COLOR if status.outdated or conflicts else COMPATIBLE_COLOR
        self.file_status_label.setStyleSheet(f'color: {color}; font-weight: bold;')
        self.file_status_label.setToolTip(input_error or ('See Details for migration or downstream-update guidance.'
                                                         if status.outdated or conflicts else ''))
        count = f'{len(files)} result ' + ('file' if len(files) == 1 else 'files')
        self.file_size_label.setText(f"Run size: {self._run_size_bytes / 1024**3:.2f} GiB" if self._run_size_bytes >= 1024**3 else
                                     f"Run size: {self._run_size_bytes / 1024**2:.1f} MiB")
        channels: dict[str, None] = {}
        images = {}
        for path in files:
            if path.name not in cst.IMAGE_NAMES:
                continue
            if path.parent not in images or path.name == cst.FITS_ARRAY_RAW:
                images[path.parent] = path
        for path in images.values():
            try:
                if path not in self._file_channel_cache:
                    self._file_channel_cache[path] = tuple(FitsIO.from_path(path).channel_labels)
                labels = self._file_channel_cache[path]
                channels.update(dict.fromkeys(labels))
            except Exception:
                pass
        self.file_channels_label.setText('Channels: ' + (', '.join(sorted(channels)) if channels else '—'))
        self.file_channels_label.setToolTip('Channel labels found in this selection’s saved images, including older and compacted arrays.')
        self.adapter.saved_image_channels = list(channels)
        self._refresh_channel_choices()

    def _file_details_text(self) -> str:
        """
        File details text.
        """
        status = self._run_status
        if status is None:
            return ''
        selected = self.run_browser.selected_path or status.root
        scope = selected.parent if selected.is_file() else selected
        files = [path for path in status.files if path.parent == scope or scope in path.parents]
        lines = []
        input_error = self._raw_input_error()
        if input_error:
            lines.append(input_error)
        if status.outdated:
            lines.append('This run contains files or an experiment layout incompatible with the current FITS version. The entire run is read-only.')
            lines.append('You can keep viewing the existing images and masks, or use Manage files → Migrate to FITS 4.')
            lines.append('Migration changes the folder structure, metadata, paths and condition tags. It preserves image pixels and measurement values. You may optionally rebuild the complete workflow from the original acquisitions. A full rebuild can take a long time, and final results may change slightly with different processing settings or versions. Existing results are backed up before replacement.')
        elif self._artifact_report is not None and self._artifact_report.conflicts:
            lines.append('Some saved results have missing inputs or no longer match their input revisions. Existing files remain viewable. Use Manage files → Rebuild outdated results… to review affected processing, or review the same choices when starting the pipeline.')
            lines.append(self._artifact_report.describe())
        count = f'{len(files)} result ' + ('file' if len(files) == 1 else 'files')
        lines += [f'Selection: {scope}', count + (' available for read-only use.' if status.outdated else '.'),
                  self.file_channels_label.text()]
        history = snapshots(status.root, scope)
        if history:
            lines.append(f'Retained backups: {len(history)} snapshots, approximately {sum(entry.size for entry in history)/1024**2:.1f} MiB')
            lines.append('Compact keeps retained history. Use Manage files to review, restore or delete it.')
        return '\n\n'.join(lines)

    @Slot()
    def _show_file_details(self) -> None:
        """
        Show file details.
        """
        if self._run_status is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Experiment file details')
        layout = QVBoxLayout(dialog)
        content = QPlainTextEdit(self._file_details_text())
        content.setReadOnly(True)
        layout.addWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        size_resizable_dialog(dialog, 760, 460)
        dialog.exec()

    @Slot()
    def _manage_files(self) -> None:
        """
        Manage files.
        """
        if self._running or not self.adapter.run_dir:
            return
        self._sync_identity()
        compatibility = inspect_run_compatibility(Path(self.adapter.run_dir))
        if not compatibility.outdated and self._save_settings() is None:
            return
        previous_step = self._current_step
        selected = self.run_browser.selected_path
        try:
            changed = manage_files(Path(self.adapter.run_dir),
                                   self.run_browser.selected_path,
                                   self,
                                   run_processing=self._run_maintenance_plan,
                                   )
            if changed:
                self._append_log('Experiment files updated. Measurements were reused for path/tag-only changes.')
        except PipelineCancelled as error:
            self._append_log(str(error))
        except Exception as error:
            ReportDialog(None, str(error), self, title='File update needs review').exec()
        finally:
            settings = run_settings_path(Path(self.adapter.run_dir))
            if settings.is_file():
                self._load_settings_path(settings, run_dir=Path(self.adapter.run_dir))
            else:
                self._refresh_run_inventory()
                self._refresh_phase_access()
            self._show_step(previous_step)
            if selected is not None and selected.exists():
                self.run_browser.select_path(selected)
            else:
                self.run_browser.select_path(Path(self.adapter.run_dir))

    def _run_maintenance_plan(self, plan: ProcessingPlan) -> None:
        """
        Run reviewed maintenance through the existing worker without a second completion dialog.
        """
        self._refresh_run_inventory()
        self._refresh_phase_access()
        self._maintenance_plan = plan
        try:
            self._run_pipeline()
            if self._thread is None:
                raise ValueError('Complete the required processing settings, then try this action again through Manage files.')
            loop = QEventLoop(self)
            self._thread.finished.connect(loop.quit)
            loop.exec()
            if not self._last_run_succeeded:
                raise ValueError('Processing did not finish. Completed work is preserved; review Manage files to continue.')
        finally:
            self._maintenance_plan = None

    @Slot(object)
    def _enqueue_mask_request(self, request: MaskCollectionRequest) -> None:
        """
        Enqueue mask request.
        """
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
        """
        Set mask expected count.
        """
        self._mask_expected_count = count
        if self._mask_collection is not None:
            self._mask_collection.set_expected_experiments(count)

    @Slot(object)
    def _enqueue_track_edit_request(self, request: TrackEditRequest) -> None:
        """
        Enqueue track edit request.
        """
        if self._worker is None or self._worker.interaction.cancelled.is_set():
            return
        self._track_edit_queue.append(request)
        self._open_next_track_edit()

    def _open_next_track_edit(self) -> None:
        """
        Open next track edit.
        """
        if self._tracking_editor is not None or not self._track_edit_queue:
            return
        from fits.gui.viewer.tracking import TrackingViewerWindow

        request = self._track_edit_queue.pop(0)
        window = TrackingViewerWindow(experiments_dir=self.adapter.run_dir,
                                      tracking_path=request.tracking_path,
                                      parent=self,
                                      editing_enabled=True,
                                      pipeline_request=request,
                                      )
        window.tracking_finalized.connect(self._tracking_edit_finalized)
        self._tracking_editor = window
        window.show()

    @Slot(object)
    def _tracking_edit_finalized(self, outcome: TrackEditOutcome) -> None:
        """
        Tracking edit finalized.
        """
        if self._worker is not None:
            self._worker.interaction.resolve_track_edit(outcome)
        self._tracking_editor = None
        QTimer.singleShot(0, self._open_next_track_edit)

    @Slot()
    def _confirm_emergency_stop(self) -> None:
        """
        Confirm an immediate shutdown of FITS and its worker processes.
        """
        answer = QMessageBox.warning(self,
                                      "Stop and exit FITS?",
                                      "Stop all processing and close FITS immediately?\n\n"
                                      "Completed results will be kept. The current step may be incomplete, "
                                      "and unsaved settings or edits will be lost.\n\n"
                                      "Restart FITS to run processing again.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No,
                                      )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            terminate_application()
        except psutil.Error as error:
            QMessageBox.critical(self, "Could not stop FITS", str(error))

    @Slot()
    def _cancel_pipeline(self) -> None:
        """
        Cancel pipeline.
        """
        if self._worker is not None:
            self._worker.interaction.cancel()
            self.run_button.setText("Stopping…")
            self._append_log("Stopping pipeline. Any step already running must finish; no further work will start.")

    @Slot()
    def _mask_input_complete(self) -> None:
        """
        Mask input complete.
        """
        if self._mask_collection is not None and not self._mask_collection._ended:
            self._mask_collection.no_more_requests()

    def _close_mask_collection(self) -> None:
        """
        Close mask collection.
        """
        if self._mask_collection is not None:
            self._mask_collection._ended = True
            self._mask_collection.close()
            self._mask_collection.deleteLater()
            self._mask_collection = None

    def _close_tracking_editor(self) -> None:
        """
        Close tracking editor.
        """
        self._track_edit_queue.clear()
        if self._tracking_editor is not None:
            self._tracking_editor._pipeline_resolved = True
            self._tracking_editor.close()
            self._tracking_editor.deleteLater()
            self._tracking_editor = None

    @Slot()
    def _pipeline_cancelled(self) -> None:
        """
        Pipeline cancelled.
        """
        self._set_activity_active(False)
        self._close_mask_collection()
        self._close_tracking_editor()
        self._run_cancelled = True
        self._append_log("Pipeline cancelled. Completed work has been kept.")

    @Slot()
    def _pipeline_finished(self) -> None:
        """
        Pipeline finished.
        """
        self._set_activity_active(False)
        self._close_mask_collection()
        self._close_tracking_editor()
        result = self._current_run_result()
        had_errors = not result.successful
        self._last_run_succeeded = result.successful
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
    @Slot(str, str)
    def _pipeline_failed(self, message: str, details: str) -> None:
        """
        Pipeline failed.
        """
        self._set_activity_active(False)
        self._close_mask_collection()
        self._close_tracking_editor()
        self._append_log(details)
        self._refresh_phase_access()
        self._refresh_report_button()
        self._run_error = message + ("\n\n" + details if details and details != message else "")

    @Slot()
    def _thread_finished(self) -> None:
        """
        Thread finished.
        """
        thread = self._thread
        if thread is not None:
            # finished can arrive before Qt's native worker cleanup is done.
            thread.wait()
        result = self._current_run_result()
        show_completion = (not self._conversion_run or not result.successful) and self._maintenance_plan is None and not self._upgrading
        self._worker = None
        self._thread = None
        self._refresh_run_inventory()
        self._set_running(False)
        if self._advance_after_conversion and self._conversion_is_current():
            self._show_step(cst.StepName.REGISTER_TIME)
        self._advance_after_conversion = False
        self._conversion_run = False
        self._pending_conversion = None
        if thread is not None:
            thread.deleteLater()
        if show_completion:
            show_run_result(result, Path(self.adapter.run_dir or "."), self, manage_files=self._manage_files)

    def _current_run_result(self) -> RunResult:
        """
        Classify this run from its shared progress, cancellation and diagnostic data.
        """
        return summarize_run(self._run_progress or RunProgress(), Path(self.adapter.run_dir or "."),
                             error=self._run_error, cancelled=self._run_cancelled)

    @Slot(str)
    def _append_log(self, message: str) -> None:
        """
        Append log.
        """
        self.console.appendPlainText(message)

    def _set_running(self, running: bool) -> None:
        """
        Set running.
        """
        if running and self._segmentation_preview_pending:
            self._clear_segmentation_preview_request()
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
        """
        Set activity active.
        """
        if not active:
            self.pipeline_progress.finish()
        self.activity_indicator.setRange(0, 0 if active else 1)
        if not active:
            self.activity_indicator.setValue(0)
        self.activity_indicator.setVisible(active)

    def _update_run_button_text(self) -> None:
        """
        Update run button text.
        """
        if self._running or self._thread is not None:
            return
        converting = self._current_step == cst.StepName.CONVERT
        self.run_button.setText("Next" if converting else "Run pipeline")
        steps = (cst.StepName.CONVERT,) if converting else cst.WORKFLOW_ORDER
        missing = [error for step in steps for error in self.adapter.missing_user_fields(step)]
        input_error = self._raw_input_error()
        if input_error and (converting or self.adapter.step_enabled(cst.StepName.CONVERT)):
            missing.append(input_error)
        self.navigation_status.setStyleSheet("color: #e57373;" if input_error else "color: #b8b8b8;")
        if converting and not self.adapter.step_enabled(cst.StepName.CONVERT) and not self._conversion_is_current():
            missing.append("Enable Convert before continuing.")
        label_job = (self._channel_labels_window is not None
                     and self._channel_labels_window._job is not None
                     and self._channel_labels_window._job.isRunning())
        outdated = self._run_status is not None and self._run_status.outdated
        if outdated and not self._upgrading:
            if converting:
                self.run_button.setEnabled(not label_job)
                self.run_button.setToolTip("Inspect processing settings. This run remains read-only; no conversion or processing will run.")
                self.navigation_status.setText("Read-only: inspect Convert and processing settings.")
                return
            missing.append('This entire run is outdated/read-only. Use Manage files to migrate it.')
        self.run_button.setEnabled(not missing and not label_job)
        action_help = (
            "Continue to processing. Reuse the converted images when conversion settings "
            "are unchanged; otherwise run Convert first."
            if converting else
            "Run the normal pipeline using all enabled steps and their overwrite settings.")
        self.run_button.setToolTip(action_help + ("\n\nBefore continuing:\n" + "\n".join(missing) if missing else ""),
                                   )
        self.navigation_status.setText(
            input_error.split("\n", 1)[0] + " See Details for affected files." if input_error and converting else
            ("Converted images are ready." if self._conversion_is_current()
             else "Next converts your images before processing.") if converting else "")

    def _latest_report(self) -> Path | None:
        """
        Latest report.
        """
        if not self.adapter.run_dir:
            return None
        log_root = str(self.adapter.runtime_value("log_dir")).strip()
        root = Path(log_root).expanduser() if log_root else Path(self.adapter.run_dir)
        reports = sorted(reports_dir(root).glob("fits_report_*.txt"))
        return reports[-1] if reports else None

    def _refresh_report_button(self) -> None:
        """
        Refresh report button.
        """
        self.report_button.setEnabled(not self._running and self._thread is None)

    def _tracking_artifacts(self, root: Path | None = None) -> list[Path]:
        """
        Tracking artifacts.
        """
        if root is None:
            if not self.adapter.run_dir:
                return []
            root = Path(self.adapter.run_dir)
        if not root.is_dir():
            return []
        try:
            names = (cst.FITS_MASK_TRACK_EDITED_FILTERED,
                     cst.FITS_MASK_TRACK_EDITED,
                     *cst.TRACKING_NAMES, *cst.SEGMENTATION_NAMES,
                     cst.FITS_MASKS_COMPACTED, *reversed(cst.IMAGE_STAGE_NAMES), cst.FITS_ARRAY_NAME,
                     cst.FITS_REFERENCE_TEMPLATE.format(label="*"), cst.FITS_ROI_TEMPLATE.format(label="*"))
            return [path for name in names for path in sorted(root.rglob(name))
                    if not is_internal_path(path, root)]
        except OSError:
            return []

    def _refresh_tracking_viewer_button(self) -> None:
        """
        Refresh tracking viewer button.
        """
        self.tracking_viewer_button.setEnabled(not self._running and self._thread is None)

    @Slot()
    def _open_channel_labels(self) -> None:
        """
        Open channel labels.
        """
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
        """
        Channel labels saved.
        """

        window = self._channel_labels_window
        old_labels = window.plan.labels if window is not None and window.plan is not None else ()
        mapping = {old: new_labels[index] for index, old in old_labels}
        self._sync_identity()
        rename_settings_document(self.adapter.document, mapping)
        self._populate_from_adapter()

    @Slot()
    def _open_tracking_viewer(self, path: Path | None = None) -> None:
        """
        Open tracking viewer.
        """
        from fits.gui.viewer.tracking import TrackingViewerWindow

        if path is None and not self.adapter.run_dir.strip():
            QMessageBox.information(
                self, "Choose a run folder",
                "Choose your experiment or run folder first using Browse or drag and drop. "
                "Tracking Viewer can then look for saved tracking results.")
            return
        selected = path or self.run_browser.selected_path
        patterns = (*cst.MASK_NAMES, *cst.IMAGE_NAMES,
                    cst.FITS_REFERENCE_TEMPLATE.format(label="*"), cst.FITS_ROI_TEMPLATE.format(label="*"))
        if (selected is None or not any(selected.match(pattern) for pattern in patterns)
                or not selected.is_file()):
            root = selected if selected is not None and selected.is_dir() else None
            artifacts = self._tracking_artifacts(root)
            selected = artifacts[0] if artifacts else None
        if selected is None:
            QMessageBox.information(
                self, "No image or mask found",
                "No FITS image or mask was found in the selected experiment or run folder.\n\n"
                "Convert your acquisition with Next, or select an experiment containing saved results.")
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
        self._tracking_viewer = TrackingViewerWindow(experiments_dir=self.adapter.run_dir,
                                                     tracking_path=selected,
                                                     editing_enabled=False,
                                                     selection_enabled=True,
                                                     )
        self._tracking_viewer.show()
        self._tracking_viewer.raise_()
        self._tracking_viewer.activateWindow()

    @Slot()
    def _open_latest_report(self) -> None:
        """
        Open latest report.
        """
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
        """
        Open a selected image, report or Parquet table with its appropriate viewer.
        """
        if not isinstance(path, (str, Path)):
            return
        report = Path(path)
        if report.is_file() and report.suffix.lower() == '.parquet':
            open_parquet(report, self)
            return
        patterns = (*cst.IMAGE_NAMES, *cst.MASK_NAMES,
                    cst.FITS_REFERENCE_TEMPLATE.format(label="*"), cst.FITS_ROI_TEMPLATE.format(label="*"))
        if report.is_file() and any(report.match(pattern) for pattern in patterns):
            self._open_tracking_viewer(report)
            return
        if report.is_file() and report.name.startswith("fits_report_") and report.suffix == ".txt":
            self._show_report(report)

    def _show_report(self, path: Path) -> None:
        """
        Show report.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "Cannot open report", str(error))
            return
        ReportDialog(path, content, self).exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Stop active work and handle the window close event.
        """
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(self,
                                    "Pipeline is running",
                                    "Wait for the pipeline to finish before closing FITS.",
                                    )
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
        if self._segmentation_preview_pending:
            self._clear_segmentation_preview_request()
        super().closeEvent(event)
