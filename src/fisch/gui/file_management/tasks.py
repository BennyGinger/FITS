"""Responsive execution of reviewed file writes for shared GUI dialogs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar
from PySide6.QtCore import QThread
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout, QWidget

_TaskResult = TypeVar("_TaskResult")


class _FileWorker(QThread):
    def __init__(self, action: Callable[[], Any], parent: QWidget) -> None:
        """
        Initialize the _FileWorker state and dependencies.
        """
        super().__init__(parent)
        self.action = action
        self.error: Exception | None = None
        self.result: Any = None
    def run(self) -> None:
        """
        Execute the background worker operation.
        """
        try:
            self.result = self.action()
        except Exception as error:
            self.error = error



class _Busy(QDialog):
    worker: _FileWorker
    def reject(self) -> None:
        """
        Reject.
        """
        if not self.worker.isRunning():
            super().reject()
    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Stop active work and handle the window close event.
        """
        if self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)



def run_file_task(action: Callable[[], _TaskResult],
                  parent: QWidget | None = None,
                  *,
                  title: str = 'Updating experiment files',
                  message: str = 'Updating files and verifying the result…',
                  ) -> _TaskResult:
    """
    Run reviewed file operations in a worker while keeping progress responsive.
    """
    dialog = _Busy(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(message))
    progress = QProgressBar()
    progress.setRange(0, 0)
    layout.addWidget(progress)
    worker = _FileWorker(action, dialog)
    dialog.worker = worker
    worker.finished.connect(dialog.accept)
    worker.start()
    dialog.exec()
    worker.wait()
    if worker.error is not None:
        raise worker.error
    return worker.result

