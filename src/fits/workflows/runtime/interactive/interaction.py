"""Thread-safe communication between the workflow and mask-drawing UI."""

import logging
from queue import Queue
from threading import Event
from typing import Callable

from fits.workflows.runtime.interactive.messages import (
    MaskCollectionOutcome, MaskCollectionRequest)
from fits.workflows.runtime.errors import PipelineCancelled


logger = logging.getLogger(__name__)


class MaskInteraction:
    """
    Exchange mask requests, outcomes, completion, and cancellation signals.
    """

    def __init__(self, request: Callable[[MaskCollectionRequest], None],
                 input_complete: Callable[[], None] = lambda: None,
                 expected_count: Callable[[int], None] = lambda count: None) -> None:
        self.request = request
        self.input_complete = input_complete
        self.expected_count = expected_count
        self.cancelled = Event()
        self.finished = Event()
        self.outcomes = Queue()

    def resolve(self, outcome: MaskCollectionOutcome) -> None:
        """
        Publish a completed mask-drawing outcome to the workflow.
        """
        logger.info('Mask drawing submitted for %s.', outcome.request.image_path)
        self.outcomes.put(outcome)

    def finish(self) -> None:
        """
        Signal that no further interactive drawing will occur.
        """
        self.finished.set()

    def cancel(self) -> None:
        """
        Request cancellation of the interactive workflow.
        """
        self.cancelled.set()

    def check_cancelled(self) -> None:
        """
        Raise when cancellation has been requested.
        """
        if self.cancelled.is_set():
            raise PipelineCancelled("Pipeline cancelled. Completed artifacts have been kept.")
