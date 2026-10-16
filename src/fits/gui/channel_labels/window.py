"""Small reusable editor for run-wide channel labels."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from fits.channel_labels import apply_labels, files_to_update, inspect_run, validate_labels
from fits.channel_labels import LabelPlan


class _Job(QThread):
    inspected = Signal(object)
    saved = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, object)

    def __init__(self, root: Path, plan: LabelPlan | None = None,
                 labels: dict[int, str] | None = None, parent=None):
        super().__init__(parent)
        self.root, self.plan, self.labels = root, plan, labels

    def run(self) -> None:
        try:
            if self.plan is None:
                self.inspected.emit(inspect_run(self.root))
            else:
                self.saved.emit(apply_labels(self.plan, self.labels or {},
                                             progress=self.progress.emit))
        except Exception as error:
            self.failed.emit(str(error))


class ChannelLabelsWindow(QMainWindow):
    labels_saved = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, run_dir: str | Path, parent=None):
        super().__init__(parent)
        self.root = Path(run_dir).expanduser().resolve()
        self.plan: LabelPlan | None = None
        self._job: _Job | None = None
        self._fields: dict[int, QLineEdit] = {}
        self._last_save_count: int | None = None
        self.setWindowTitle("FITS channel labels")
        self.resize(650, 520)
        host = QWidget()
        layout = QVBoxLayout(host)
        self.status = QLabel(f"Inspecting {self.root}…")
        self.status.setWordWrap(True)
        self.status.setFixedHeight(44)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.rename_progress = QProgressBar()
        self.rename_progress.setTextVisible(False)
        self.rename_progress.setFixedHeight(8)
        self.rename_progress.setFixedWidth(150)
        self.rename_progress.setStyleSheet(
            "QProgressBar { background: #233040; border: 1px solid #405773; "
            "border-radius: 3px; }"
            "QProgressBar::chunk { background: #399df2; border-radius: 2px; }")
        self.rename_progress.hide()
        self.form = QFormLayout()
        layout.addLayout(self.form)
        layout.addWidget(QLabel("Files to update"))
        self.files = QPlainTextEdit()
        self.files.setReadOnly(True)
        layout.addWidget(self.files)
        buttons = QHBoxLayout()
        self.rescan_button = QPushButton("Rescan")
        self.rescan_button.clicked.connect(self.inspect)
        buttons.addWidget(self.rescan_button)
        buttons.addStretch()
        buttons.addWidget(self.rename_progress)
        self.save_button = QPushButton("Save labels")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        self.setCentralWidget(host)
        QTimer.singleShot(0, self.inspect)

    def _start(self, job: _Job) -> None:
        self._job = job
        self.busy_changed.emit(True)
        self.rescan_button.setEnabled(False)
        self.save_button.setEnabled(False)
        job.inspected.connect(self._inspected)
        job.saved.connect(self._saved)
        job.failed.connect(self._failed)
        job.progress.connect(self._progress)
        job.finished.connect(self._job_finished)
        job.start()

    def _job_finished(self) -> None:
        self.rescan_button.setEnabled(True)
        self.busy_changed.emit(False)

    def inspect(self) -> None:
        self.plan = None
        self.rename_progress.hide()
        self.status.setText(f"Inspecting {self.root}…")
        self.files.clear()
        self._start(_Job(self.root, parent=self))

    def _inspected(self, plan: LabelPlan) -> None:
        self.plan = plan
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields.clear()
        for index, label in plan.labels:
            field = QLineEdit(label)
            self.form.addRow(f"Source channel {index}", field)
            self._fields[index] = field
            field.textChanged.connect(self._preview_changes)
        prefix = (f"Updated {self._last_save_count} files. "
                  if self._last_save_count is not None else "")
        self.status.setText(
            f"{prefix}Validated {len(plan.tiffs)} TIFFs; {len(plan.files)} FITS files inspected.")
        self._last_save_count = None
        self._preview_changes()

    def _preview_changes(self) -> None:
        if self.plan is None:
            return
        proposed = {index: field.text() for index, field in self._fields.items()}
        try:
            paths = files_to_update(self.plan, proposed)
        except ValueError:
            self.files.setPlainText("Enter unique, non-empty channel labels to preview files.")
            self.save_button.setEnabled(False)
            return
        preview = ("\n".join(str(path.relative_to(self.root)) for path in paths)
                   if paths else "No files need updating.")
        self.files.setPlainText(
            f"Scanned {len(self.plan.files)} FITS files.\n\n{preview}")
        self.save_button.setEnabled(bool(paths))

    def save(self) -> None:
        if self.plan is None:
            return
        try:
            labels = validate_labels(self.plan, {index: field.text()
                                                 for index, field in self._fields.items()})
        except ValueError as error:
            QMessageBox.warning(self, "Invalid labels", str(error))
            return
        self.status.setText("Saving labels throughout the run…")
        self.rename_progress.setRange(0, 0)
        self.rename_progress.show()
        self._start(_Job(self.root, self.plan, labels, parent=self))

    def _progress(self, completed: int, total: int, path: Path) -> None:
        self.rename_progress.setRange(0, total)
        self.rename_progress.setValue(completed)
        self.status.setText(
            f"Renaming files… {completed}/{total}: {path.relative_to(self.root)}")

    def _saved(self, paths: tuple[Path, ...]) -> None:
        labels = {index: field.text().strip() for index, field in self._fields.items()}
        self._last_save_count = len(paths)
        self.status.setText(f"Updated {len(paths)} files.")
        self.labels_saved.emit(labels)
        QTimer.singleShot(0, self.inspect)

    def _failed(self, message: str) -> None:
        self.rename_progress.hide()
        if self._job is not None and self._job.plan is None:
            self.status.setText("Could not inspect channel labels.")
            self.files.setPlainText(message)
        else:
            self.status.setText("Channel-label save failed.")
            QMessageBox.critical(self, "Channel labels", message)

    def closeEvent(self, event) -> None:
        if self._job is not None and self._job.isRunning():
            QMessageBox.information(self, "Operation in progress", "Wait for this operation to finish.")
            event.ignore()
            return
        super().closeEvent(event)
