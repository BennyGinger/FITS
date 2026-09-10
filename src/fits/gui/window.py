from __future__ import annotations

import logging
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fits.environment.constant import WORKFLOW_ORDER, StepName
from fits.gui.settings_adapter import SAVED_SETTINGS_NAME, STEP_LAYOUTS, SettingsAdapter
from fits.gui.settings_editor import RuntimeSettingsEditor, StepSettingsEditor
from fits.gui.run_browser import RunDirectoryBrowser
from fits.pipeline import start_pipeline
from fits.workflows.interactive import MaskInteraction, PipelineCancelled
from fits.workflows.errors import StepExecutionError
from fits.settings.models import SegmentSettings


def _user_error_message(error: BaseException) -> str:
    """Return the contextual step error hidden inside executor wrappers."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        if isinstance(current, StepExecutionError):
            return str(current)
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return str(error)


class LogEmitter(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    """Forward formatted records to the Qt event loop."""

    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self.emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.message.emit(self.format(record))
        except Exception:
            self.handleError(record)


class PipelineWorker(QObject):
    finished = Signal()
    cancelled = Signal()
    mask_requested = Signal(object)
    mask_input_complete = Signal()
    failed = Signal(str, str)

    def __init__(self, settings_path: Path, log_handler: logging.Handler, demo_step_delay: float = 0.0) -> None:
        super().__init__()
        self.settings_path = settings_path
        self.log_handler = log_handler
        self.demo_step_delay = demo_step_delay
        self.interaction = MaskInteraction(self.mask_requested.emit, self.mask_input_complete.emit)

    @Slot()
    def run(self) -> None:
        try:
            start_pipeline(
                settings_path=self.settings_path,
                console_handler=self.log_handler,
                mask_interaction=self.interaction,
                demo_step_delay=self.demo_step_delay,
            )
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(_user_error_message(error), traceback.format_exc())
        else:
            self.finished.emit()


class FitsMainWindow(QMainWindow):
    """Main FITS desktop window."""

    def __init__(
        self,
        adapter: SettingsAdapter | None = None,
        parent: QWidget | None = None,
        demo_step_delay: float = 0.0,
    ) -> None:
        super().__init__(parent)
        self.demo_step_delay = demo_step_delay
        self._mask_collection = None
        self.adapter = adapter or SettingsAdapter()
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        self._step_items: dict[StepName, QTreeWidgetItem] = {}
        self._editors: dict[StepName, StepSettingsEditor] = {}
        self.runtime_editor: RuntimeSettingsEditor | None = None
        self._segmentation_tuner = None

        self.setWindowTitle("FITS")
        self.resize(1200, 850)
        self._build_ui()
        self._populate_from_adapter()

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setMinimumHeight(230)
        top_splitter.setMaximumHeight(280)

        identity_panel = QWidget()
        identity = QVBoxLayout(identity_panel)
        identity.setContentsMargins(0, 0, 8, 0)
        identity_form = QFormLayout()

        run_dir_row = QWidget()
        run_dir_layout = QHBoxLayout(run_dir_row)
        run_dir_layout.setContentsMargins(0, 0, 0, 0)
        self.run_dir_edit = QLineEdit()
        self.run_dir_edit.returnPressed.connect(self._run_dir_entered)
        self.run_dir_edit.textChanged.connect(self._run_dir_text_changed)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._browse_run_dir)
        run_dir_layout.addWidget(self.run_dir_edit)
        run_dir_layout.addWidget(self.browse_button)
        identity_form.addRow("Run directory", run_dir_row)

        self.user_name_edit = QLineEdit()
        identity_form.addRow("User name", self.user_name_edit)
        identity.addLayout(identity_form)

        self.runtime_host = QWidget()
        self.runtime_host_layout = QVBoxLayout(self.runtime_host)
        self.runtime_host_layout.setContentsMargins(0, 6, 0, 0)
        identity.addWidget(self.runtime_host)
        identity.addStretch()
        top_splitter.addWidget(identity_panel)

        self.run_browser = RunDirectoryBrowser()
        top_splitter.addWidget(self.run_browser)
        top_splitter.setStretchFactor(0, 2)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([760, 400])
        outer.addWidget(top_splitter)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.step_tree = QTreeWidget()
        self.step_tree.setHeaderLabel("Pipeline steps")
        self.step_tree.setMinimumWidth(230)
        self.step_tree.currentItemChanged.connect(self._selected_step_changed)
        self.step_tree.itemChanged.connect(self._step_enabled_changed)
        main_splitter.addWidget(self.step_tree)

        self.settings_stack = QStackedWidget()
        main_splitter.addWidget(self.settings_stack)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([230, 900])

        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        vertical_splitter.addWidget(main_splitter)

        console_container = QWidget()
        console_layout = QVBoxLayout(console_container)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.addWidget(QLabel("Console / activity log"))
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
        self.run_button.clicked.connect(self._run_pipeline)
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch()
        buttons.addWidget(self.run_button)
        outer.addLayout(buttons)

        self.setCentralWidget(central)

    def _populate_from_adapter(self) -> None:
        self.run_dir_edit.setText(self.adapter.run_dir)
        self.user_name_edit.setText(self.adapter.user_name)
        self.run_browser.set_root(self.adapter.run_dir)

        self.step_tree.blockSignals(True)
        self.step_tree.clear()
        self._step_items.clear()
        if self.runtime_editor is not None:
            self.runtime_host_layout.removeWidget(self.runtime_editor)
            self.runtime_editor.deleteLater()
        for editor in self._editors.values():
            self.settings_stack.removeWidget(editor)
            editor.deleteLater()
        self._editors.clear()

        self.runtime_editor = RuntimeSettingsEditor(self.adapter)
        self.runtime_host_layout.addWidget(self.runtime_editor)

        for step in WORKFLOW_ORDER:
            item = QTreeWidgetItem([STEP_LAYOUTS[step].title])
            item.setData(0, Qt.ItemDataRole.UserRole, step.value)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                0,
                Qt.CheckState.Checked
                if self.adapter.step_enabled(step)
                else Qt.CheckState.Unchecked,
            )
            self.step_tree.addTopLevelItem(item)
            self._step_items[step] = item

            editor = StepSettingsEditor(self.adapter, step)
            if step == StepName.SEGMENT:
                tune_row = QWidget()
                tune_layout = QHBoxLayout(tune_row)
                tune_layout.setContentsMargins(0, 0, 0, 0)
                tune_layout.setSpacing(16)
                self.segtune_button = QPushButton("Tune segmentation…")
                self.segtune_button.clicked.connect(self._open_segmentation_tuner)
                tune_description = QLabel(
                    "Preview segmentation on an image and adjust Cellpose settings. "
                    "Apply and close copies your changes back here.")
                tune_description.setWordWrap(True)
                tune_description.setStyleSheet("color: #b8b8b8;")
                tune_layout.addWidget(tune_description, 1)
                tune_layout.addWidget(
                    self.segtune_button, 0, Qt.AlignmentFlag.AlignVCenter)
                editor.layout().insertWidget(1, tune_row)
            editor.set_editable(self.adapter.step_enabled(step))
            self.settings_stack.addWidget(editor)
            self._editors[step] = editor

        self.step_tree.blockSignals(False)
        if self.step_tree.topLevelItemCount():
            first_item = self.step_tree.topLevelItem(0)
            if first_item is not None:
                self.step_tree.setCurrentItem(first_item)

    @Slot()
    def _open_segmentation_tuner(self) -> None:
        from fits.gui.viewer.segmentation_window import SegmentationTunerWindow

        self._sync_identity()
        try:
            settings = SegmentSettings.model_validate(
                self.adapter.as_mapping()["segment"]["params"])
        except ValueError as error:
            QMessageBox.critical(self, "Cannot open segmentation tuner", str(error))
            return
        tuner = SegmentationTunerWindow(
            experiments_dir=self.adapter.run_dir or None,
            segment_settings=settings,
            parent=self,
            close_on_apply=True,
        )
        tuner.setWindowModality(Qt.WindowModality.WindowModal)
        tuner.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tuner.settings_applied.connect(self._apply_segmentation_settings)
        tuner.destroyed.connect(lambda: setattr(self, "_segmentation_tuner", None))
        self._segmentation_tuner = tuner
        tuner.show()

    @Slot(object)
    def _apply_segmentation_settings(self, settings: SegmentSettings) -> None:
        def store(path: str, value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    store(f"{path}.{key}", child)
            else:
                self.adapter.set_field_value(
                    StepName.SEGMENT, path, "None" if value is None else value)

        for name, value in settings.to_payload_dict().items():
            store(name, value)
        self._populate_from_adapter()
        self.step_tree.setCurrentItem(self._step_items[StepName.SEGMENT])
        self._append_log("Applied settings from the segmentation tuner.")

    def _step_from_item(self, item: QTreeWidgetItem) -> StepName:
        return StepName(item.data(0, Qt.ItemDataRole.UserRole))

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _selected_step_changed(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        step = self._step_from_item(current)
        self.settings_stack.setCurrentWidget(self._editors[step])

    @Slot(QTreeWidgetItem, int)
    def _step_enabled_changed(self, item: QTreeWidgetItem, column: int) -> None:
        del column
        step = self._step_from_item(item)
        enabled = item.checkState(0) == Qt.CheckState.Checked
        self.adapter.set_step_enabled(step, enabled)
        self._editors[step].set_editable(enabled)
        self.step_tree.setCurrentItem(item)
        self._selected_step_changed(item, None)

    @Slot()
    def _browse_run_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select FITS run directory",
            self.run_dir_edit.text() or str(Path.home()),
        )
        if directory:
            self._switch_run_dir(directory)

    @Slot()
    def _run_dir_entered(self) -> None:
        self._switch_run_dir(self.run_dir_edit.text())

    @Slot(str)
    def _run_dir_text_changed(self, value: str) -> None:
        if value.strip():
            return
        self.adapter.run_dir = ""
        self.run_browser.set_root("")

    def _switch_run_dir(self, directory: str) -> None:
        raw_directory = directory.strip()
        if not raw_directory:
            self.run_dir_edit.clear()
            self.adapter.run_dir = ""
            self.run_browser.set_root("")
            return

        resolved = Path(raw_directory).expanduser().resolve()
        self.run_dir_edit.setText(str(resolved))
        self.adapter.run_dir = str(resolved)
        self.run_browser.set_root(resolved)

        saved_settings = resolved / SAVED_SETTINGS_NAME
        if saved_settings.is_file():
            self._load_settings_path(saved_settings, run_dir=resolved)

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
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load FITS settings",
            self.run_dir_edit.text() or str(Path.home()),
            "TOML settings (*.toml)",
        )
        if not path:
            return
        self._load_settings_path(Path(path))

    def _load_settings_path(self, path: Path, *, run_dir: Path | None = None) -> None:
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
            return
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
            QMessageBox.critical(
                self,
                "Invalid settings",
                f"{STEP_LAYOUTS[step].title}:\n{error}",
            )
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
        self._sync_identity()
        errors = self.adapter.validate_for_run()
        if errors:
            QMessageBox.warning(self, "Cannot run FITS", "\n".join(errors))
            return
        settings_path = self._save_settings()
        if settings_path is None:
            return

        emitter = LogEmitter(self)
        emitter.message.connect(self._append_log)
        handler = QtLogHandler(emitter)
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )

        thread = QThread(self)
        worker = PipelineWorker(settings_path, handler, self.demo_step_delay)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.mask_requested.connect(self._enqueue_mask_request)
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
        self._set_running(True)
        self._append_log("Starting FITS pipeline…")
        thread.start()

    @Slot(object)
    def _enqueue_mask_request(self, request) -> None:
        from fits.gui.viewer.collection_window import MaskCollectionWindow
        if self._worker is None or self._worker.interaction.finished.is_set() or self._worker.interaction.cancelled.is_set():
            return
        if self._mask_collection is None:
            window = MaskCollectionWindow(parent=self, preview=False, run_dir=Path(self.adapter.run_dir))
            interaction = self._worker.interaction
            window.experiment_finalized.connect(interaction.resolve)
            window.collection_finished.connect(interaction.finish)
            window.cancellation_requested.connect(self._cancel_pipeline)
            self._mask_collection = window
            window.show()
        self._mask_collection.enqueue_experiment(request)

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

    @Slot()
    def _pipeline_cancelled(self) -> None:
        self._close_mask_collection()
        self._append_log("Pipeline cancelled. Completed work has been kept.")

    @Slot()
    def _pipeline_finished(self) -> None:
        self._close_mask_collection()
        self._append_log("FITS pipeline completed successfully.")

    @Slot(str, str)
    def _pipeline_failed(self, message: str, details: str) -> None:
        self._close_mask_collection()
        self._append_log(details)
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
        self._worker = None
        self._thread = None
        self._set_running(False)
        if thread is not None:
            thread.deleteLater()

    @Slot(str)
    def _append_log(self, message: str) -> None:
        self.console.appendPlainText(message)

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.load_button.setEnabled(not running)
        self.save_button.setEnabled(not running)
        self.browse_button.setEnabled(not running)
        self.run_dir_edit.setEnabled(not running)
        self.user_name_edit.setEnabled(not running)
        self.step_tree.setEnabled(not running)
        self.settings_stack.setEnabled(not running)
        self.run_button.setText("Running…" if running else "Run pipeline")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self,
                "Pipeline is running",
                "Wait for the pipeline to finish before closing FITS.",
            )
            event.ignore()
            return
        super().closeEvent(event)
