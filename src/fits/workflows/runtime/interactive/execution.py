"""Execute automatic phases and contain per-experiment failures."""

import logging
from threading import Event
from time import monotonic

from fits.workflows.definitions.models import item_runner_for
from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import PipelineCancelled
from fits.workflows.runtime.interactive.interaction import PipelineInteraction
from fits.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage
from fits.workflows.runtime.scheduler.planning import RuntimeStep

logger = logging.getLogger(__name__)


class PhaseExecutor:
    """
    Run automatic steps with cancellation, progress, and failure reporting.
    """

    def __init__(self, 
                 interaction: PipelineInteraction, 
                 progress: RunProgress,
                 stop_event: Event, 
                 step_delay_seconds: float = 0.0
                 ) -> None:
        self.interaction = interaction
        self.progress = progress
        self.stop_event = stop_event
        self.step_delay_seconds = step_delay_seconds

    def pause(self) -> None:
        self.interaction.check_cancelled()
        if self.stop_event.is_set():
            raise PipelineCancelled("Preparation stopped.")
        if not self.step_delay_seconds:
            return
        logger.info("Demo pause: %.1f seconds.", self.step_delay_seconds)
        deadline = monotonic() + self.step_delay_seconds
        while monotonic() < deadline:
            if self.stop_event.wait(min(.1, max(0, deadline - monotonic()))):
                raise PipelineCancelled("Preparation stopped.")
            self.interaction.check_cancelled()

    def run(self, 
            current: list[ExperimentState], 
            steps: tuple[RuntimeStep, ...],
            stage: WorkflowStage, 
            experiment_id: str
            ) -> list[ExperimentState]:
        if not steps:
            return current
        self.progress.update(experiment_id, stage, StageStatus.ACTIVE)
        try:
            for step in steps:
                produced = []
                for state in current:
                    self.interaction.check_cancelled()
                    if self.stop_event.is_set():
                        raise PipelineCancelled("Preparation stopped.")
                    name = step.spec.profile.step_name
                    logger.info("Starting %s for %s", name, state.experiment_id)
                    runner = item_runner_for(step.spec)
                    outputs = runner(step.settings, state, step.spec.profile)
                    produced.extend(outputs)
                    logger.info("Finished %s for %s", name, state.experiment_id)
                    self.pause()
                current = produced
        except PipelineCancelled:
            self.progress.update(experiment_id, stage, StageStatus.SKIPPED)
            raise
        except Exception as error:
            self.progress.update(
                experiment_id, stage, StageStatus.FAILED, error=str(error))
            raise
        self.progress.update(experiment_id, stage, StageStatus.COMPLETED)
        return current

    def contain_failure(self, experiment_id: str, stage: WorkflowStage,
                        error: Exception) -> None:
        self.progress.skip_pending(experiment_id, 
                                   detail=f"not run because {stage.value} failed")
        logger.error("Experiment failed during %s and will be omitted; remaining experiments will continue: %s | experiment=%s",
                        stage.value, error, experiment_id,
                        exc_info=error.__traceback__ is not None,)
