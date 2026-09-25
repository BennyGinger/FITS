"""Validate manual masks and run the analysis phase."""

import logging

from fits.environment.constant import StepName
from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import PipelineCancelled
from fits.workflows.runtime.interactive.execution import PhaseExecutor
from fits.workflows.runtime.interactive.masks import validate_mask_outcome
from fits.workflows.runtime.interactive.messages import MaskCollectionOutcome, MaskCollectionRequest
from fits.workflows.runtime.interactive.plan import InteractivePlan
from fits.workflows.runtime.progress import StageStatus, WorkflowStage
from fits.workflows.runtime.scheduler.planning import RuntimeStep

logger = logging.getLogger(__name__)


class ExperimentFinalizer:
    """
    Join finalized inputs with computed states and execute analysis.
    """

    def __init__(self, plan: InteractivePlan, executor: PhaseExecutor) -> None:
        self.plan = plan
        self.executor = executor

    def finalize(self, 
                 request: MaskCollectionRequest,
                 outcome: MaskCollectionOutcome,
                 computed: list[ExperimentState] | None,
                 final_states: list[ExperimentState]
                 ) -> None:
        try:
            validate_mask_outcome(request, outcome)
        except Exception as error:
            self.executor.progress.update(request.experiment_id, 
                                          WorkflowStage.DRAWING,
                                          StageStatus.FAILED, 
                                          error=str(error))
            self.executor.progress.skip_pending(request.experiment_id,
                                                detail="not run because mask validation failed")
            logger.error("Experiment mask validation failed and analysis will be omitted; remaining experiments will continue: %s | experiment=%s",
                            error, request.experiment_id, exc_info=True)
            return

        missing = self._record_mask_result(request, outcome)
        selected = self._analysis_steps(request, outcome)
        if selected and computed is not None:
            try:
                final_states.extend(self.executor.run(
                    computed, selected, WorkflowStage.ANALYSIS,
                    request.experiment_id))
            except PipelineCancelled:
                raise
            except Exception as error:
                self.executor.contain_failure(request.experiment_id, WorkflowStage.ANALYSIS, error)
            else:
                self._record_partial_analysis(request, outcome, missing)
            return

        status = (StageStatus.PARTIAL if missing and computed is not None
                  else StageStatus.SKIPPED)
        self.executor.progress.update(
            request.experiment_id, WorkflowStage.ANALYSIS, status,
            detail=("; ".join(missing) + "; configured analysis could not run")
            if missing else None)
        if computed is not None:
            final_states.extend(computed)

    def _record_mask_result(self, 
                            request: MaskCollectionRequest,
                            outcome: MaskCollectionOutcome
                            ) -> list[str]:
        missing = []
        if request.requires_reference and not outcome.reference_paths:
            missing.append("reference mask input missing")
        if outcome.skipped_rois:
            missing.append("ROI mask input missing")
        skipped = outcome.skipped_references + outcome.skipped_rois
        status = (StageStatus.SKIPPED
                  if skipped and not (outcome.reference_paths or outcome.roi_paths)
                  else StageStatus.COMPLETED)
        if self.plan.mask_collection_required:
            self.executor.progress.update(
                request.experiment_id, WorkflowStage.DRAWING, status,
                detail="; ".join(missing) or None)
            logger.info("Masks finalized for %s: %d references, %d ROIs, %d skipped requests.",
                        request.experiment_id, len(outcome.reference_paths),
                        len(outcome.roi_paths), skipped)
        return missing

    def _analysis_steps(self, 
                        request: MaskCollectionRequest,
                        outcome: MaskCollectionOutcome,
                        ) -> tuple[RuntimeStep, ...]:
        if outcome.reference_paths:
            return self.plan.analysis
        if request.requires_reference:
            logger.warning("Omitting distance profiling for %s: no reference mask was finalized.",
                            request.experiment_id)
        return tuple(step for step in self.plan.analysis
                     if step.spec.profile.step_name != StepName.DISTANCE_PROFILE)

    def _record_partial_analysis(self, 
                                 request: MaskCollectionRequest,
                                 outcome: MaskCollectionOutcome,
                                 missing: list[str]
                                 ) -> None:
        if not missing:
            return
        detail = "; ".join(missing)
        if not outcome.reference_paths and request.requires_reference:
            detail += "; distance profile skipped; extraction completed"
        elif not outcome.roi_paths and request.uses_roi:
            detail += "; distance profile completed over the whole image"
        self.executor.progress.update(
            request.experiment_id, WorkflowStage.ANALYSIS,
            StageStatus.PARTIAL, detail=detail)
