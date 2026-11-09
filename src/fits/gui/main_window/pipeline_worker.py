"""Background Qt worker that owns one pipeline execution."""

from __future__ import annotations

from fits.workflows.file_management.rebuild import ProcessingPlan
from collections.abc import Callable
from typing import Any
import logging
import os
from multiprocessing import get_context
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from time import monotonic
import traceback
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from fits.pipeline import start_pipeline
from fits.channel_labels.lock import run_write_guard
from fits.settings.loader import load_settings
from fits.workflows.runtime.errors import StepExecutionError
from fits.workflows.runtime.interactive import PipelineCancelled, PipelineInteraction
from fits.workflows.runtime.progress import RunProgress
from fits.gui.main_window.emergency_stop import terminate_process_tree
from fits.gui.main_window.pipeline_process import run_pipeline_process, send_interaction_commands


def user_error_message(error: BaseException) -> str:
    """
    Return the contextual step error hidden inside executor wrappers.
    """
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        if isinstance(current, StepExecutionError):
            return str(current)
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return str(error)


class PipelineWorker(QObject):
    finished = Signal()
    cancelled = Signal()
    mask_requested = Signal(object)
    track_edit_requested = Signal(object)
    mask_input_complete = Signal()
    mask_expected_count = Signal(int)
    failed = Signal(str, str)
    artifact_decision_requested = Signal(object)

    def __init__(self,
                 settings_path: Path,
                 log_handler: logging.Handler,
                 demo_step_delay: float = 0.0,
                 *,
                 convert_only: bool = False,
                 force_conversion: bool = False,
                 upgrading: bool = False,
                 maintenance: ProcessingPlan | None = None,
                 runner: Callable[..., Any] | None = None,
                 ) -> None:
        """
        Initialize the PipelineWorker state and dependencies.
        """
        super().__init__()
        self.settings_path = settings_path
        self.log_handler = log_handler
        self.demo_step_delay = demo_step_delay
        self.convert_only = convert_only
        self.force_conversion = force_conversion
        self.upgrading = upgrading
        self.maintenance = maintenance
        self._runner = runner
        self._process: BaseProcess | None = None
        self._isolated_group = False
        self.interaction = PipelineInteraction(self.mask_requested.emit,
                                               self.mask_input_complete.emit,
                                               self.mask_expected_count.emit,
                                               self.track_edit_requested.emit,
                                               decision_request=self.artifact_decision_requested.emit,
                                               )
        self.progress = RunProgress()

    @Slot()
    def run(self) -> None:
        """
        Supervise an isolated pipeline and stop it promptly when cancellation is requested.
        """
        try:
            name, payload = self._run_process()
        except Exception as error:
            self.failed.emit(user_error_message(error), traceback.format_exc())
            return
        if name == 'cancelled':
            self.cancelled.emit()
        elif name == 'failed':
            self.failed.emit(*payload)
        else:
            self.finished.emit()

    def _run_process(self) -> tuple[str, Any]:
        """
        Keep interaction and logging responsive while a disposable worker owns processing.
        """
        context = get_context('spawn')
        parent, child = context.Pipe()
        options = {'demo_step_delay': self.demo_step_delay, 'convert_only': self.convert_only,
                   'force_conversion': self.force_conversion, 'upgrading': self.upgrading,
                   'maintenance': self.maintenance}
        process = context.Process(target=run_pipeline_process,
                                   args=(child, self.settings_path, options, self._runner),
                                   name='fits-pipeline')
        self._process = process
        self._isolated_group = False
        try:
            process.start()
            child.close()
            return self._supervise(parent, process)
        finally:
            if process.pid is not None:
                process.join(timeout=0.5)
                if process.is_alive():
                    terminate_process_tree(process.pid, isolated_group=self._isolated_group)
                process.join(timeout=3)
                if self._isolated_group:
                    terminate_process_tree(process.pid, isolated_group=True)
                process.close()
            parent.close()
            child.close()
            self._process = None

    def _supervise(self, connection: Connection, process: BaseProcess) -> tuple[str, Any]:
        """
        Relay events and briefly allow cooperative cancellation before terminating the worker.
        """
        stopping: float | None = None
        masks_finished = False
        while True:
            if self.interaction.cancelled.is_set() and stopping is None:
                stopping = monotonic()
                try:
                    connection.send(('cancel', None))
                except (BrokenPipeError, OSError):
                    return 'cancelled', None
            if stopping is not None and monotonic() - stopping >= 0.3:
                assert process.pid is not None
                terminate_process_tree(process.pid, isolated_group=self._isolated_group)
                return 'cancelled', None
            try:
                send_interaction_commands(connection, self.interaction)
                if self.interaction.mask_finished.is_set() and not masks_finished:
                    connection.send(('masks_finished', None))
                    masks_finished = True
                if connection.poll(0.05):
                    name, payload = connection.recv()
                    if name in ('finished', 'cancelled', 'failed'):
                        return ('cancelled', None) if stopping is not None else (name, payload)
                    self._process_event(name, payload)
                elif not process.is_alive():
                    if stopping is not None:
                        return 'cancelled', None
                    return 'failed', (f'Pipeline process exited unexpectedly ({process.exitcode}).', '')
            except (EOFError, BrokenPipeError, OSError):
                if stopping is not None or self.interaction.cancelled.is_set():
                    return 'cancelled', None
                process.join(timeout=0.1)
                return 'failed', (f'Pipeline process exited unexpectedly ({process.exitcode}).', '')

    def _process_event(self, name: str, payload: Any) -> None:
        """
        Update the existing GUI-facing progress objects and interaction signals.
        """
        if name == 'started':
            self._isolated_group = os.name == 'posix'
        elif name == 'log':
            self.log_handler.handle(logging.makeLogRecord(payload))
        elif name == 'progress':
            experiments, display = payload
            self.progress.replace_snapshot(experiments)
            self.progress.display.replace_snapshot(display)
        elif name == 'mask_request':
            self.mask_requested.emit(payload)
        elif name == 'masks_complete':
            self.mask_input_complete.emit()
        elif name == 'mask_count':
            self.mask_expected_count.emit(payload)
        elif name == 'tracking_request':
            self.track_edit_requested.emit(payload)
        elif name == 'decision_request':
            self.artifact_decision_requested.emit(payload)

    @Slot()
    def run_inline(self) -> None:
        """
        Execute without process transport for callers that already own execution isolation.
        """
        try:
            root = Path(load_settings(self.settings_path)["run_dir"]).expanduser().resolve()
            with run_write_guard(root):
                options: dict[str, Any] = {'maintenance': self.maintenance} if self.maintenance is not None else {}
                (self._runner or start_pipeline)(settings_path=self.settings_path,
                               console_handler=self.log_handler,
                               interaction=self.interaction,
                               demo_step_delay=self.demo_step_delay,
                               run_progress=self.progress,
                               convert_only=self.convert_only,
                               force_conversion=self.force_conversion,
                               terminal_progress=False,
                               upgrading=self.upgrading,
                               **options,
                               )
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(user_error_message(error), traceback.format_exc())
        else:
            self.finished.emit()
