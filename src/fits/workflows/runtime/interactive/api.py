"""
Orchestrate automatic phases and interactive workflow inputs.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Event
from typing import Any, Mapping

from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import PipelineCancelled
from fits.workflows.runtime.interactive.execution import PhaseExecutor
from fits.workflows.runtime.interactive.finalization import ExperimentFinalizer
from fits.workflows.runtime.interactive.interaction import PipelineInteraction
from fits.workflows.runtime.interactive.joining import PendingItem, collect_mask_outcomes, finalize_ready, start_next_prepared
from fits.workflows.runtime.interactive.messages import MaskCollectionOutcome
from fits.workflows.runtime.interactive.plan import InteractivePlan
from fits.workflows.runtime.interactive.preparation import PreparationProducer, PreparedItem
from fits.workflows.runtime.interactive.progress import input_progress_id
from fits.workflows.runtime.interactive.reporting import report_interactive_run
from fits.workflows.runtime.interactive.tracking_edits import TrackingEditCoordinator
from fits.workflows.runtime.progress import RunProgress
from fits.workflows.runtime.scheduler import resolve_runtime_steps



def run_interactive_workflow(config: Mapping[str, Any], 
                             states: list[ExperimentState],
                             interaction: PipelineInteraction, 
                             *, 
                             step_delay_seconds: float = 0.0,
                             progress: RunProgress | None = None
                             ) -> list[ExperimentState]:
    """
    Run the configured phases and join their interactive results.
    """
    if step_delay_seconds < 0:
        raise ValueError("Demo step delay cannot be negative.")

    plan = InteractivePlan.from_steps(resolve_runtime_steps(config))
    progress = progress or RunProgress()
    for state in states:
        progress.add(input_progress_id(state), plan.required_stages)
    interaction.mask_expected_count(len(states) if plan.mask_collection_required else 0)

    stop_preparation = Event()
    producer_done = Event()
    prepared: Queue[PreparedItem] = Queue()
    executor = PhaseExecutor(interaction, progress, stop_preparation, step_delay_seconds)
    producer = PreparationProducer(states, 
                                   plan, 
                                   interaction, 
                                   executor, 
                                   prepared, 
                                   producer_done)
    edit_step = plan.editing[0] if plan.editing else None
    tracking_edits = TrackingEditCoordinator(edit_step, interaction, progress)
    finalizer = ExperimentFinalizer(plan, executor)

    pending: dict[Path, PendingItem] = {}
    mask_outcomes: dict[Path, MaskCollectionOutcome] = {}
    final_states: list[ExperimentState] = []

    with ThreadPoolExecutor(max_workers=1,
                            thread_name_prefix="fits-preparation") as pool:
        preparation = pool.submit(producer.run)
        try:
            while not producer_done.is_set() or not prepared.empty() or pending:
                interaction.check_cancelled()
                if preparation.done():
                    preparation.result()

                collect_mask_outcomes(interaction, mask_outcomes)
                tracking_edits.collect_outcomes()
                finalize_ready(
                    pending, mask_outcomes, plan, interaction,
                    tracking_edits, finalizer, executor, final_states)
                start_next_prepared(
                    prepared, pending, plan, tracking_edits, executor)

            preparation.result()
            interaction.check_cancelled()
        except PipelineCancelled:
            progress.skip_unfinished()
            raise
        finally:
            stop_preparation.set()

    report_interactive_run(progress, states, final_states)
    return final_states
