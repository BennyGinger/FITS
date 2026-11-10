"""Request, collect, and persist interactive tracking edits."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from fisch.environment.constant import ARTI_IMG, ARTI_TRACK, DIST_PIPELINE
from fisch.tasks.tracking.edit import register_tracking_edit
from fisch.workflows.experiments import ExperimentState
from fisch.workflows.metadata._values import distribution_version, utc_now
from fisch.workflows.runtime.interactive.interaction import PipelineInteraction
from fisch.workflows.runtime.interactive.messages import TrackEditOutcome, TrackEditRequest
from fisch.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage
from fisch.workflows.runtime.run_decision import decide_run
from fisch.workflows.runtime.scheduler.planning import RuntimeStep
from fisch.workflows.definitions.inputs import resolve_inputs


class TrackingEditCoordinator:
    """
    Own the lifecycle of tracking-edit requests and their saved outcomes.
    """
    def __init__(self,
                 step: RuntimeStep | None,
                 interaction: PipelineInteraction,
                 progress: RunProgress,
                 ) -> None:
        """
        Initialize the TrackingEditCoordinator state and dependencies.
        """
        self.step = step
        self.interaction = interaction
        self.progress = progress
        self.received: dict[Path, TrackEditOutcome] = {}

    def collect_outcomes(self) -> None:
        """
        Collect outcomes.
        """
        while not self.interaction.track_edit_outcomes.empty():
            outcome = self.interaction.track_edit_outcomes.get_nowait()
            self.received[outcome.request.tracking_path] = outcome

    def request(self, states: list[ExperimentState] | None) -> tuple[TrackEditRequest, ...]:
        """
        Return the current request.
        """
        if self.step is None or states is None:
            return ()
        requests = []
        for state in states:
            if state.execution_scope is not None and self.step.spec.profile.step_name not in state.execution_scope.get(state.workdir,
                                                                                                                       (),
                                                                                                                       ):
                continue
            decision = decide_run(state, self.step.spec.profile, self.step.settings.overwrite)
            if decision.is_complete:
                continue

            tracking_path = state.artifact(ARTI_TRACK)
            profile = self.step.spec.profile
            inputs = resolve_inputs(state, profile)
            image_path = inputs.get(profile.additional_artifacts[0]) if profile.additional_artifacts else state.artifact(ARTI_IMG)
            if tracking_path is None or not tracking_path.is_file():
                raise ValueError(f"No tracking artifact is available for {state.experiment_id}.")

            if image_path is None or not image_path.is_file():
                raise ValueError("No image artifact is available for {state.experiment_id}.")

            request = TrackEditRequest(experiment_id=state.experiment_id,
                                       tracking_path=tracking_path,
                                       image_path=image_path,
                                       overwrite=self.step.settings.overwrite,
                                       pipeline_metadata=state.metadata_dump,
                                       )
            requests.append(request)
            self.interaction.track_edit_request(request)

        if requests:
            self.progress.update(requests[0].experiment_id,
                                 WorkflowStage.PROCESS,
                                 StageStatus.ACTIVE,
                                 detail="waiting for tracking edits",
                                 )
        elif states:
            self.progress.update(states[0].experiment_id, WorkflowStage.PROCESS, StageStatus.COMPLETED)
        return tuple(requests)

    def finalize(self,
                 states: list[ExperimentState] | None,
                 requests: tuple[TrackEditRequest, ...],
                 ) -> list[ExperimentState] | None:
        """
        Return the current finalize.
        """
        if states is None or self.step is None or not requests:
            return states
        if any(request.tracking_path not in self.received 
               for request in requests):
            return None
        by_path = {request.tracking_path: request for request in requests}
        finalized = []
        for state in states:
            tracking_path = state.artifact(ARTI_TRACK)
            request = by_path.get(tracking_path) if tracking_path is not None else None
            if request is None:
                finalized.append(state)
                continue
            outcome = self.received.pop(request.tracking_path)
            if outcome.request != request:
                raise ValueError("Tracking edit result does not match its experiment request.")

            artifact_path, metadata = self._artifact_and_metadata(request, outcome)
            finalized.append(register_tracking_edit(state, self.step.spec.profile, artifact_path, metadata))
        self.progress.update(requests[0].experiment_id, WorkflowStage.PROCESS, StageStatus.COMPLETED)
        return finalized

    @staticmethod
    def _artifact_and_metadata(request: TrackEditRequest,
                               outcome: TrackEditOutcome,
                               ) -> tuple[Path, dict[str, Any]]:
        """
        Artifact and metadata.
        """
        if outcome.edited_path is not None:
            return outcome.edited_path, dict(outcome.metadata or {})
        return request.tracking_path, {"source_tracking_artifact": request.tracking_path.name,
                                        "mask_channels": [],
                                        "prediction_image_channels": [],
                                        "operations_used": [],
                                        "filter_condition": None,
                                        "decision": "use_original",
                                        "timestamp": utc_now(),
                                        "pipeline_version": distribution_version(DIST_PIPELINE),}
