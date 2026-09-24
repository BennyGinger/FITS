"""Log the final interactive run report and detect total failure."""

import logging

from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import AllExperimentsFailed
from fits.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage

logger = logging.getLogger(__name__)


def report_interactive_run(progress: RunProgress,
                           inputs: list[ExperimentState],
                           outputs: list[ExperimentState]) -> None:
    """
    Log stage totals and raise when no input produced a final state.
    """
    snapshot = progress.snapshot()
    for stage in WorkflowStage:
        counts = {status: 0 for status in StageStatus}
        failures = []
        for experiment in snapshot:
            stage_progress = experiment.stage(stage)
            if stage_progress is None:
                continue
            counts[stage_progress.status] += 1
            if stage_progress.status == StageStatus.FAILED:
                failures.append(f"{experiment.experiment_id}: {stage_progress.error}")
        logger.info("Run report %s: %d completed, %d partial, %d skipped, %d failed.",
                    stage.value, counts[StageStatus.COMPLETED],
                    counts[StageStatus.PARTIAL], counts[StageStatus.SKIPPED],
                    counts[StageStatus.FAILED])
        for failure in failures:
            logger.error("Run report %s failure: %s", stage.value, failure)
    if inputs and not outputs:
        failures = [f"{experiment.experiment_id}: {stage.error}"
                    for experiment in snapshot
                    for stage in experiment.stages.values()
                    if stage.status == StageStatus.FAILED]
        detail = "; ".join(failures) or "no experiment produced a final state"
        raise AllExperimentsFailed(f"All experiments failed. {detail}")
