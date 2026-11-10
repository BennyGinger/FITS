"""Shared GUI and interactive-CLI presentation of the completed pipeline run."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fisch.gui.dialogs import size_resizable_dialog
from fisch.gui.run_result.report import ReportDialog
from fisch.workflows.file_management.api import can_compact
from fisch.workflows.runtime.progress.outcome import RunOutcome, RunResult


class RunResultDialog(QDialog):
    """
    Show the run outcome and offer its full report or successful-run file management.
    """

    def __init__(self, result: RunResult, root: Path, parent: QWidget | None = None) -> None:
        """
        Present the same outcome and available actions in both interactive interfaces.
        """
        super().__init__(parent)
        self.manage_requested = False
        self.setWindowTitle('Pipeline run finished')
        layout = QVBoxLayout(self)
        actions = QGridLayout()
        actions.setColumnStretch(0, 1)
        actions.setHorizontalSpacing(20)
        actions.setVerticalSpacing(16)
        layout.addLayout(actions)
        message = QLabel(result.message)
        message.setWordWrap(True)
        color = '#8fd6a0' if result.successful else '#f0b66a' if result.outcome != RunOutcome.FAILED else '#f29595'
        message.setStyleSheet(f'color: {color}; font-weight: bold;')
        actions.addWidget(message, 0, 0, Qt.AlignmentFlag.AlignTop)
        report = QPushButton('Full report…')
        report.setToolTip('Inspect completed, skipped and failed stages and the full diagnostic information for this run.')
        report.clicked.connect(lambda: ReportDialog(None, result.report, self).exec())
        actions.addWidget(report, 0, 1, Qt.AlignmentFlag.AlignTop)
        if result.successful and can_compact(root):
            hint = QLabel('You can compact the experiments to free disk space by removing intermediate files while keeping essential results.')
            hint.setWordWrap(True)
            actions.addWidget(hint, 1, 0, Qt.AlignmentFlag.AlignTop)
            manage = QPushButton('Manage files…')
            manage.setToolTip('Open experiment file management to compact results, update files or manage retained backups.')
            manage.clicked.connect(self._request_management)
            actions.addWidget(manage, 1, 1, Qt.AlignmentFlag.AlignTop)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        size_resizable_dialog(self, 640, 300)

    def _request_management(self) -> None:
        """
        Close this dialog before the owner opens its existing file-management flow.
        """
        self.manage_requested = True
        self.accept()


def show_run_result(result: RunResult,
                    root: Path,
                    parent: QWidget | None = None,
                    *,
                    manage_files: Callable[[], object],
                    ) -> None:
    """
    Display completion and return navigation or CLI lifecycle control to the caller.
    """
    dialog = RunResultDialog(result, root, parent)
    dialog.exec()
    if dialog.manage_requested:
        try:
            manage_files()
        except Exception as error:
            ReportDialog(None, str(error), parent, title='File management needs review').exec()
