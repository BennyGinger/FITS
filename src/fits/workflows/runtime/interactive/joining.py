"""Join prepared experiments with mask and tracking-edit outcomes."""

import logging
from pathlib import Path
from queue import Empty, Queue

from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import PipelineCancelled
from fits.workflows.runtime.interactive.execution import PhaseExecutor
from fits.workflows.runtime.interactive.finalization import ExperimentFinalizer
from fits.workflows.runtime.interactive.interaction import PipelineInteraction
from fits.workflows.runtime.interactive.masks import existing_mask_outcome
from fits.workflows.runtime.interactive.messages import MaskCollectionOutcome, MaskCollectionRequest, TrackEditRequest
from fits.workflows.runtime.interactive.plan import InteractivePlan
from fits.workflows.runtime.interactive.preparation import PreparedItem
from fits.workflows.runtime.interactive.tracking_edits import TrackingEditCoordinator
from fits.workflows.runtime.progress import WorkflowStage

logger = logging.getLogger(__name__)
PendingItem = tuple[MaskCollectionRequest,
                    list[ExperimentState] | None,
                    tuple[TrackEditRequest, ...],]


def collect_mask_outcomes(interaction: PipelineInteraction,
                          outcomes: dict[Path, MaskCollectionOutcome]
                          ) -> None:
    """
    Drain currently available mask outcomes into their request lookup.
    """
    while True:
        try:
            outcome = interaction.mask_outcomes.get_nowait()
        except Empty:
            return
        outcomes[outcome.request.image_path] = outcome


def finalize_ready(pending: dict[Path, PendingItem],
                    mask_outcomes: dict[Path, MaskCollectionOutcome],
                    plan: InteractivePlan,
                    interaction: PipelineInteraction,
                    tracking_edits: TrackingEditCoordinator,
                    finalizer: ExperimentFinalizer,
                    executor: PhaseExecutor,
                    final_states: list[ExperimentState]
                    ) -> None:
    """
    Finalize every pending experiment whose manual inputs have arrived.
    """
    for key, (request, computed, edit_requests) in list(pending.items()):
        outcome = _mask_outcome(key, request, mask_outcomes, plan, interaction)
        if outcome is None:
            continue
        try:
            edited = tracking_edits.finalize(computed, edit_requests)
        except Exception as error:
            executor.contain_failure(request.experiment_id, WorkflowStage.PROCESS, error)
            del pending[key]
            continue
        if edit_requests and edited is None:
            if plan.mask_collection_required:
                mask_outcomes[key] = outcome
            continue
        finalizer.finalize(request, outcome, edited, final_states)
        del pending[key]


def start_next_prepared(prepared: Queue[PreparedItem], 
                        pending: dict[Path, PendingItem],
                        plan: InteractivePlan, 
                        tracking_edits: TrackingEditCoordinator,
                        executor: PhaseExecutor
                        ) -> None:
    """
    Run computation for the next prepared image and request editing.
    """
    try:
        state, request = prepared.get(timeout=.1)
    except Empty:
        return
    try:
        computed = executor.run([state], 
                                plan.computation,
                                WorkflowStage.PROCESS, 
                                request.experiment_id)
    except PipelineCancelled:
        raise
    except Exception as error:
        executor.contain_failure(request.experiment_id, 
                                 WorkflowStage.PROCESS, 
                                 error)
        computed = None
    try:
        edit_requests = tracking_edits.request(computed)
    except PipelineCancelled:
        raise
    except Exception as error:
        executor.contain_failure(request.experiment_id, 
                                 WorkflowStage.PROCESS, 
                                 error)
        computed = None
        edit_requests = ()
    pending[request.image_path] = (request, computed, edit_requests)


def _mask_outcome(key: Path, 
                  request: MaskCollectionRequest,
                  outcomes: dict[Path, MaskCollectionOutcome],
                  plan: InteractivePlan,
                  interaction: PipelineInteraction
                  ) -> MaskCollectionOutcome | None:
    if not plan.mask_collection_required:
        return existing_mask_outcome(request)
    outcome = outcomes.pop(key, None)
    if outcome is None and interaction.mask_finished.is_set():
        logger.info("Drawing ended early; using existing masks for %s.",
                    request.experiment_id)
        return existing_mask_outcome(request)
    return outcome
