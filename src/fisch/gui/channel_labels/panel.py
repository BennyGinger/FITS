"""Run-wide channel renaming embedded in Manage files or the standalone launcher."""

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from fisch.channel_labels import LabelPlan, apply_labels, files_to_update, inspect_run, validate_labels
from fisch.gui.settings.conversion_channels import ConversionChannelsWidget
from fisch.workflows.checks.raw_inputs import inspect_raw_inputs


class _LabelJob(QThread):
    """Inspect or rename channel references without blocking the interface."""

    inspected = Signal(object, object)
    saved = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, object)

    def __init__(self, root: Path, plan: LabelPlan | None = None, labels: dict[int, str] | None = None, parent: QWidget | None = None) -> None:
        """
        Store the already validated rename or the run to inspect.
        """
        super().__init__(parent)
        self.root, self.plan, self.labels = root, plan, labels

    def run(self) -> None:
        """
        Inspect channel references or apply an explicitly confirmed rename.
        """
        try:
            if self.plan is None:
                plan = inspect_run(self.root)
                report = inspect_raw_inputs(self.root)
                self.inspected.emit(plan, report.expected_channel_colors)
            else:
                self.saved.emit(apply_labels(self.plan, self.labels or {}, progress=self.progress.emit))
        except Exception as error:
            self.failed.emit(str(error))


class ChannelLabelsPanel(QWidget):
    """Review affected files and apply channel labels through the existing rename API."""

    labels_saved = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, run_dir: str | Path, parent: QWidget | None = None) -> None:
        """
        Place the compact channel table beside its explanation and file preview.
        """
        super().__init__(parent)
        self.root = Path(run_dir).expanduser().resolve()
        self.plan: LabelPlan | None = None
        self._job: _LabelJob | None = None
        self._last_save_count: int | None = None
        self._active = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("Rename existing channels throughout this run's images, masks, tables and saved settings. "
                      "Channel order and image pixels stay the same. Enter unique, non-empty labels, "
                      "then review the affected files before saving.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        columns = QHBoxLayout()
        self.channels = ConversionChannelsWidget([])
        self.channels.setMaximumWidth(450)
        self.channels.table.setMinimumWidth(300)
        columns.addWidget(self.channels, 1, Qt.AlignmentFlag.AlignTop)
        self.files = QPlainTextEdit()
        self.files.setReadOnly(True)
        self.files.setMinimumHeight(70)
        self.files.setMaximumHeight(120)
        columns.addWidget(self.files, 1)
        layout.addLayout(columns)
        buttons = QHBoxLayout()
        self.status = QLabel("Inspecting channel labels…")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        buttons.addWidget(self.status, 1)
        self.rename_progress = QProgressBar()
        self.rename_progress.setTextVisible(False)
        self.rename_progress.setFixedSize(150, 8)
        self.rename_progress.hide()
        buttons.addWidget(self.rename_progress)
        self.rescan_button = QPushButton("Rescan")
        self.rescan_button.clicked.connect(self.inspect)
        buttons.addWidget(self.rescan_button)
        self.save_button = QPushButton("Save new labels")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        self.channels.value_changed.connect(self._preview_changes)
        QTimer.singleShot(0, self.inspect)

    @property
    def is_busy(self) -> bool:
        """
        Report whether the panel still owns a running file operation.
        """
        return self._job is not None and self._job.isRunning()

    @property
    def is_saving(self) -> bool:
        """
        Distinguish a write operation from a background inspection.
        """
        return self.is_busy and self._job is not None and self._job.plan is not None

    def _start(self, job: _LabelJob) -> None:
        """
        Disable conflicting edits until inspection or saving has finished.
        """
        self._job = job
        self.rescan_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.channels.setEnabled(False)
        job.inspected.connect(self._inspected)
        job.saved.connect(self._saved)
        job.failed.connect(self._failed)
        job.progress.connect(self._progress)
        job.finished.connect(self._job_finished)
        job.start()
        self.busy_changed.emit(True)

    def _job_finished(self) -> None:
        """
        Restore editing and release finished workers before any scheduled rescan.
        """
        self.rescan_button.setEnabled(True)
        self.channels.setEnabled(self.plan is not None)
        self.busy_changed.emit(False)
        if self._job is not None and self._job.plan is not None and self._last_save_count is not None:
            QTimer.singleShot(0, self.inspect)
        elif self.plan is not None:
            self._preview_changes()

    def finish_session(self) -> None:
        """
        Cancel queued scans when the containing interface has finished closing.
        """
        self._active = False

    def inspect(self) -> None:
        """
        Refresh the run-wide label plan without overlapping another operation.
        """
        if self.is_busy or not self._active:
            return
        self.plan = None
        self.rename_progress.hide()
        self.status.setText("Inspecting channel labels…")
        self.files.clear()
        self._start(_LabelJob(self.root, parent=self))

    def _inspected(self, plan: LabelPlan, colors: list[str | None] | None) -> None:
        """
        Display labels by original source position alongside detected colours.
        """
        self.plan = plan
        self.channels.set_labels([label for _, label in plan.labels])
        self.channels.set_source(len(plan.labels), [colors[index] if colors is not None and index < len(colors) else None
                                                   for index, _ in plan.labels])
        prefix = f"Updated {self._last_save_count} files. " if self._last_save_count is not None else ""
        self.status.setText(f"{prefix}Validated {len(plan.tiffs)} TIFFs; {len(plan.files)} FIScH files inspected.")
        self._last_save_count = None
        self._preview_changes()

    def _proposed_labels(self) -> dict[int, str]:
        """
        Read table rows using the plan's stable original channel indexes.
        """
        assert self.plan is not None
        return {index: item.text() if (item := self.channels.table.item(row, 2)) is not None else ""
                for row, (index, _) in enumerate(self.plan.labels)}

    def _preview_changes(self) -> None:
        """
        List only files affected by valid proposed names.
        """
        if self.plan is None:
            return
        with QSignalBlocker(self.channels.table):
            for row, (index, _) in enumerate(self.plan.labels):
                number = self.channels.table.item(row, 0)
                label = self.channels.table.item(row, 2)
                if number is not None:
                    number.setText(str(index + 1))
                if label is not None:
                    label.setToolTip("Enter a unique, non-empty channel label.")
        try:
            paths = files_to_update(self.plan, self._proposed_labels())
        except ValueError as error:
            self.files.setPlainText(str(error))
            self.save_button.setEnabled(False)
            return
        preview = "\n".join(str(path.relative_to(self.root)) for path in paths) if paths else "No files need updating."
        self.files.setPlainText(f"Scanned {len(self.plan.files)} FIScH files.\n\n{preview}")
        self.save_button.setEnabled(bool(paths) and not self.is_busy)

    def save(self) -> None:
        """
        Confirm the proposed renames before writing any files.
        """
        if self.plan is None or self.is_busy:
            return
        try:
            labels = validate_labels(self.plan, self._proposed_labels())
        except ValueError as error:
            QMessageBox.warning(self, "Invalid labels", str(error))
            return
        changes = [f"{old} → {labels[index]}" for index, old in self.plan.labels if old != labels[index]]
        if not changes:
            return
        answer = QMessageBox.question(self, "Save new channel labels?",
                                      "Rename channels throughout this run?\n\n" + "\n".join(changes) +
                                      "\n\nImage pixels and channel order are preserved.",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Save:
            return
        self.status.setText("Saving labels throughout the run…")
        self.rename_progress.setRange(0, 0)
        self.rename_progress.show()
        self._start(_LabelJob(self.root, self.plan, labels, parent=self))

    def _progress(self, completed: int, total: int, path: Path) -> None:
        """
        Display progress while managed files are being renamed.
        """
        self.rename_progress.setRange(0, total)
        self.rename_progress.setValue(completed)
        self.status.setText(f"Renaming files… {completed}/{total}: {path.relative_to(self.root)}")

    def _saved(self, paths: tuple[Path, ...]) -> None:
        """
        Publish the old-to-new mapping before rescanning the saved files.
        """
        assert self.plan is not None
        labels = self._proposed_labels()
        mapping = {old: labels[index].strip() for index, old in self.plan.labels}
        self._last_save_count = len(paths)
        self.status.setText(f"Updated {len(paths)} files.")
        self.labels_saved.emit(mapping)

    def _failed(self, message: str) -> None:
        """
        Keep inspection or save failures visible without closing the manager.
        """
        self.rename_progress.hide()
        self.status.setText("Could not inspect channel labels." if self.plan is None else "Channel-label save failed.")
        self.files.setPlainText(message)
