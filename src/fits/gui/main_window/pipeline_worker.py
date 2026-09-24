"""Background Qt worker that owns one pipeline execution."""

import logging
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from fits.pipeline import start_pipeline
from fits.workflows.runtime.errors import StepExecutionError
from fits.workflows.runtime.interactive import PipelineCancelled, PipelineInteraction
from fits.workflows.runtime.progress import RunProgress


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

    def __init__(self, settings_path: Path, log_handler: logging.Handler,
                 demo_step_delay: float = 0.0,
                 *,
                 convert_only: bool = False,
                 ) -> None:
        super().__init__()
        self.settings_path = settings_path
        self.log_handler = log_handler
        self.demo_step_delay = demo_step_delay
        self.convert_only = convert_only
        self.interaction = PipelineInteraction(self.mask_requested.emit,
                                               self.mask_input_complete.emit,
                                               self.mask_expected_count.emit,
                                               self.track_edit_requested.emit,)
        self.progress = RunProgress()

    @Slot()
    def run(self) -> None:
        try:
            start_pipeline(settings_path=self.settings_path,
                           console_handler=self.log_handler,
                           interaction=self.interaction,
                           demo_step_delay=self.demo_step_delay,
                           run_progress=self.progress,
                           convert_only=self.convert_only,)
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(user_error_message(error), traceback.format_exc())
        else:
            self.finished.emit()
