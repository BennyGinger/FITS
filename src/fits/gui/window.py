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
from fits.pipeline import start_pipeline


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
    failed = Signal(str)

    def __init__(self, settings_path: Path, log_handler: logging.Handler) -> None:
        super().__init__()
        self.settings_path = settings_path
        self.log_handler = log_handler

    @Slot()
    def run(self) -> None:
        try:
            start_pipeline(
                settings_path=self.settings_path,
                console_handler=self.log_handler,
            )
        except Exception:
            self.failed.emit(traceback.format_exc())
        else:
            self.finished.emit()


class FitsMainWindow(QMainWindow):
    """Main FITS desktop window."""

    def __init__(
        self,
        adapter: SettingsAdapter | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter or SettingsAdapter()
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        self._step_items: dict[StepName, QTreeWidgetItem] = {}
        self._editors: dict[StepName, StepSettingsEditor] = {}
        self.runtime_editor: RuntimeSettingsEditor | None = None

        self.setWindowTitle("FITS")
        self.resize(1100, 760)
        self._build_ui()
        self._populate_from_adapter()

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)

        identity = QFormLayout()
        run_dir_row = QWidget()
        run_dir_layout = QHBoxLayout(run_dir_row)
        run_dir_layout.setContentsMargins(0, 0, 0, 0)
        self.run_dir_edit = QLineEdit()
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._browse_run_dir)
        run_dir_layout.addWidget(self.run_dir_edit)
        run_dir_layout.addWidget(self.browse_button)
        identity.addRow("Run directory", run_dir_row)

        self.user_name_edit = QLineEdit()
        identity.addRow("User name", self.user_name_edit)
        outer.addLayout(identity)

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
        vertical_splitter.setSizes([430, 250])
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

        self.step_tree.blockSignals(True)
        self.step_tree.clear()
        self._step_items.clear()
        if self.runtime_editor is not None:
            self.settings_stack.removeWidget(self.runtime_editor)
            self.runtime_editor.deleteLater()
        for editor in self._editors.values():
            self.settings_stack.removeWidget(editor)
            editor.deleteLater()
        self._editors.clear()

        runtime_item = QTreeWidgetItem(["Runtime settings"])
        runtime_item.setData(0, Qt.ItemDataRole.UserRole, "runtime")
        self.step_tree.addTopLevelItem(runtime_item)
        self.runtime_editor = RuntimeSettingsEditor(self.adapter)
        self.settings_stack.addWidget(self.runtime_editor)

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
            editor.set_editable(self.adapter.step_enabled(step))
            self.settings_stack.addWidget(editor)
            self._editors[step] = editor

        self.step_tree.blockSignals(False)
        if self.step_tree.topLevelItemCount():
            first_item = self.step_tree.topLevelItem(0)
            if first_item is not None:
                self.step_tree.setCurrentItem(first_item)

    def _step_from_item(self, item: QTreeWidgetItem) -> StepName | None:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return None if value == "runtime" else StepName(value)

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
        if step is None:
            if self.runtime_editor is not None:
                self.settings_stack.setCurrentWidget(self.runtime_editor)
            return
        self.settings_stack.setCurrentWidget(self._editors[step])

    @Slot(QTreeWidgetItem, int)
    def _step_enabled_changed(self, item: QTreeWidgetItem, column: int) -> None:
        del column
        step = self._step_from_item(item)
        if step is None:
            return
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
            self.run_dir_edit.setText(directory)
            self.adapter.run_dir = directory
            saved_settings = Path(directory) / SAVED_SETTINGS_NAME
            if saved_settings.is_file():
                self._load_settings_path(saved_settings)

    def _sync_identity(self) -> None:
        self.adapter.run_dir = self.run_dir_edit.text().strip()
        self.adapter.user_name = self.user_name_edit.text().strip()
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

    def _load_settings_path(self, path: Path) -> None:
        previous_document = self.adapter.document
        previous_source = self.adapter.source_path
        try:
            self.adapter.load(path)
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
        worker = PipelineWorker(settings_path, handler)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
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

    @Slot()
    def _pipeline_finished(self) -> None:
        self._append_log("FITS pipeline completed successfully.")

    @Slot(str)
    def _pipeline_failed(self, details: str) -> None:
        self._append_log(details)
        QMessageBox.critical(
            self,
            "Pipeline failed",
            "The FITS pipeline failed. See the activity log for details.",
        )

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
