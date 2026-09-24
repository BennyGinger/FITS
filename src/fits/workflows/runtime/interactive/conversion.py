"""Conversion-only execution used before interactive mask collection."""

import logging
from collections.abc import Mapping
from typing import Any

from fits.environment.constant import StepName
from fits.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage
from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import AllExperimentsFailed
from fits.workflows.runtime.interactive.progress import input_progress_id
from fits.workflows.runtime.scheduler import resolve_runtime_steps
from fits.workflows.definitions.models import item_runner_for


logger = logging.getLogger(__name__)


def run_conversion_only(config: Mapping[str, Any],
                        states: list[ExperimentState],
                        *,
                        step_delay_seconds: float = 0.0,
                        progress: RunProgress | None = None,
                        ) -> list[ExperimentState]:
    """
    Convert each input independently and record a conversion-only report.
    """
    if step_delay_seconds < 0:
        raise ValueError('Demo step delay cannot be negative.')
    conversion = [step for step in resolve_runtime_steps(config)
        if step.spec.profile.step_name == StepName.CONVERT]
    
    progress = progress or RunProgress()
    
    final_states: list[ExperimentState] = []
    for state in states:
        experiment_id = input_progress_id(state)
        progress.add(experiment_id, {WorkflowStage.CONVERT})
        progress.update(experiment_id, WorkflowStage.CONVERT, StageStatus.ACTIVE)
        try:
            produced = [state]
            for step in conversion:
                item_runner = item_runner_for(step.spec)
                next_states = []
                for current in produced:
                    next_states.extend(
                        item_runner(
                            step.settings, current, step.spec.profile))
                produced = next_states
            progress.update(experiment_id, WorkflowStage.CONVERT, StageStatus.COMPLETED)
            progress.replace_experiment(experiment_id,
                                        (converted.experiment_id for converted in produced))
            final_states.extend(produced)
            if step_delay_seconds:
                from time import sleep
                sleep(step_delay_seconds)
        
        except Exception as error:
            progress.update(experiment_id, WorkflowStage.CONVERT, StageStatus.FAILED,
                            error=str(error))
            logger.error("Experiment failed during conversion and will be omitted; "
                        "remaining experiments will continue: %s | experiment=%s",
                        error, experiment_id, exc_info=True)
    if states and not final_states:
        raise AllExperimentsFailed('All experiments failed during conversion.')
    return final_states
