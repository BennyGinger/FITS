"""Thread-safe communication between the workflow and interactive GUIs."""

from __future__ import annotations

from typing import Callable
import logging
from queue import Queue, Empty
from threading import Event
from fisch.workflows.runtime.interactive.messages import MaskCollectionOutcome, MaskCollectionRequest, TrackEditOutcome, TrackEditRequest
from fisch.workflows.runtime.errors import PipelineCancelled, StepExecutionError
from fisch.workflows.checks.models import PreflightReport, PreflightRequired


logger = logging.getLogger(__name__)


class PipelineInteraction:
    """
    Exchange manual-input requests, outcomes, and cancellation signals.
    """

    def __init__(self,
                 mask_request: Callable[[MaskCollectionRequest], None],
                 mask_input_complete: Callable[[], None] = lambda: None,
                 mask_expected_count: Callable[[int], None] = lambda count: None,
                 track_edit_request: Callable[[TrackEditRequest], None] | None = None,
                 decision_request: Callable | None = None,
                 ) -> None:
        """
        Initialize the PipelineInteraction state and dependencies.
        """
        self.mask_request = mask_request
        self.mask_input_complete = mask_input_complete
        self.mask_expected_count = mask_expected_count
        self.track_edit_request = track_edit_request or self._missing_track_editor
        self.cancelled = Event()
        self.mask_finished = Event()
        self.mask_outcomes = Queue()
        self.track_edit_outcomes = Queue()
        self.decision_request = decision_request
        self.decisions = Queue()

    def decide_artifacts(self, report: PreflightReport) -> str:
        """
        Ask the owning GUI thread and wait without importing Qt here.
        """
        if self.decision_request is None:
            raise PreflightRequired(report)
        self.decision_request(report)
        while True:
            self.check_cancelled()
            try:
                return self.decisions.get(timeout=0.1)
            except Empty:
                pass

    def resolve_mask(self, outcome: MaskCollectionOutcome) -> None:
        """
        Publish a completed mask-drawing outcome to the workflow.
        """
        logger.info('Mask drawing submitted for %s.', outcome.request.image_path)
        self.mask_outcomes.put(outcome)

    def finish_mask_collection(self) -> None:
        """
        Signal that no further interactive drawing will occur.
        """
        self.mask_finished.set()

    def resolve_track_edit(self, outcome: TrackEditOutcome) -> None:
        """
        Publish one completed tracking-edit decision to the workflow.
        """
        logger.info('Tracking edit submitted for %s.', outcome.request.tracking_path)
        self.track_edit_outcomes.put(outcome)

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

    @staticmethod
    def _missing_track_editor(request: TrackEditRequest) -> None:
        """
        Missing track editor.
        """
        raise StepExecutionError(f"Tracking edit for {request.experiment_id} requires the FIScH GUI.")
