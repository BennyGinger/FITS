"""Prepare image artifacts and publish mask-collection requests."""

from dataclasses import replace
import logging
from queue import Queue
from threading import Event

from fits.environment.constant import ARTI_IMG, StepName
from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import PipelineCancelled
from fits.workflows.runtime.interactive.execution import PhaseExecutor
from fits.workflows.runtime.interactive.interaction import PipelineInteraction
from fits.workflows.runtime.interactive.messages import MaskCollectionRequest
from fits.workflows.runtime.interactive.plan import InteractivePlan
from fits.workflows.runtime.interactive.progress import input_progress_id
from fits.workflows.runtime.progress import StageStatus, WorkflowStage

logger = logging.getLogger(__name__)
PreparedItem = tuple[ExperimentState, MaskCollectionRequest]


class PreparationProducer:
    """
    Run conversion/preprocessing and queue each usable prepared image.
    """

    def __init__(self, 
                 states: list[ExperimentState], 
                 plan: InteractivePlan,
                 interaction: PipelineInteraction, 
                 executor: PhaseExecutor,
                 output: Queue[PreparedItem], 
                 done: Event
                 ) -> None:
        self.states = states
        self.plan = plan
        self.interaction = interaction
        self.executor = executor
        self.output = output
        self.done = done
        self.expected = len(states) if plan.mask_collection_required else 0

    def run(self) -> None:
        try:
            for original in self.states:
                self.interaction.check_cancelled()
                self._prepare_original(original)
        finally:
            self.done.set()
            self.interaction.mask_input_complete()

    def _prepare_original(self, original: ExperimentState) -> None:
        original_id = input_progress_id(original)
        try:
            converted = self.executor.run([original], 
                                          self.plan.conversion,
                                          WorkflowStage.CONVERT, 
                                          original_id)
        except PipelineCancelled:
            raise
        except Exception as error:
            self.executor.contain_failure(original_id, WorkflowStage.CONVERT, error)
            self._adjust_expected(-1)
            return
        
        self.executor.progress.replace_experiment(original_id, 
                                                  (state.experiment_id for state in converted))
        self._adjust_expected(len(converted) - 1)
        for state in converted:
            self._prepare_converted(state)

    def _prepare_converted(self, state: ExperimentState) -> None:
        experiment_id = state.experiment_id
        try:
            prepared = self.executor.run([state], 
                                         self.plan.preprocessing,
                                         WorkflowStage.PREPROCESS, 
                                         experiment_id)
        except PipelineCancelled:
            raise
        except Exception as error:
            self.executor.contain_failure(experiment_id, WorkflowStage.PREPROCESS, error)
            self._adjust_expected(-1)
            return
        for current in prepared:
            if not self.plan.conversion and not self.plan.preprocessing:
                self.executor.pause()
            self._publish(current)

    def _publish(self, state: ExperimentState) -> None:
        image = state.artifact(ARTI_IMG)
        if image is None or not image.is_file():
            message = (f"No prepared image for {state.experiment_id}. Enable conversion first.")
            self.executor.progress.update(state.experiment_id, 
                                          WorkflowStage.PREPROCESS,
                                          StageStatus.FAILED, 
                                          error=message)
            self.executor.contain_failure(state.experiment_id, 
                                          WorkflowStage.PREPROCESS,
                                          ValueError(message))
            self._adjust_expected(-1)
            return
        settings = self.plan.settings
        request = MaskCollectionRequest.from_settings(image,
                                                      extraction=settings.get(StepName.EXTRACT),
                                                      profile=settings.get(StepName.DISTANCE_PROFILE),)
        request = replace(request, experiment_id=state.experiment_id)
        if self.plan.mask_collection_required:
            self.executor.progress.update(state.experiment_id, 
                                          WorkflowStage.DRAWING, 
                                          StageStatus.ACTIVE)
            logger.info("Ready for mask drawing: %s", state.experiment_id)
            if not self.interaction.mask_finished.is_set():
                self.interaction.mask_request(request)
        self.output.put((state, request))

    def _adjust_expected(self, delta: int) -> None:
        if not self.plan.mask_collection_required or not delta:
            return
        self.expected = max(0, self.expected + delta)
        self.interaction.mask_expected_count(self.expected)
