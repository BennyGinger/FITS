from __future__ import annotations

import logging
from typing import Any, Mapping

from fits.environment.constant import WORKFLOW_ORDER
from fits.environment.state import ExperimentState
from fits.settings.models import SettingsModel
from fits.workflows.engines.executors import execute
from fits.workflows.engines.models import StepSpec
from fits.workflows.engines.registry import REGISTRY
from fits.workflows.engines.scheduler import run_workflow_scheduler
from progress_bar import pbar


logger = logging.getLogger(__name__)



def run_workflow(effective_cfg: Mapping[str, Any], exp_states: list[ExperimentState]) -> list[ExperimentState]:
    """
    Execute the configured workflow sequentially for all experiment states.

    Each enabled workflow step is validated, then executed in the order
    defined by ``WORKFLOW_ORDER``. The returned experiment states from one
    step become the input to the next.
    
    Args:
        effective_cfg: The effective configuration with overwrite cascade applied.
        exp_states: List of experiment states to process.
    
    Returns:
        List of experiment states after processing through the workflow.
    """
    for step_name in WORKFLOW_ORDER:
        step_cfg = effective_cfg.get(step_name)

        if not isinstance(step_cfg, Mapping):
            continue

        if not step_cfg.get("enabled", False):
            continue

        spec = REGISTRY.get(step_name)

        if spec is None:
            raise ValueError(
                f"Enabled step {step_name!r} is missing from the registry."
            )

        params = step_cfg.get("params", {})

        if not isinstance(params, Mapping):
            raise TypeError(
                f"Expected '{step_name}.params' to be a mapping."
            )

        settings = spec.model_validate(params)
        exp_states = _run_step_batch(
            spec=spec,
            settings=settings,
            exp_states=exp_states,
        )
    
    return exp_states


def run_workflow_scheduler_entry(
    effective_cfg: Mapping[str, Any],
    exp_states: list[ExperimentState],
) -> list[ExperimentState]:
    """
    Execute the configured workflow using the conveyor scheduler.

    This is the scheduler-backed equivalent of ``run_workflow()``. Workflow
    execution order and step dependencies are coordinated by the scheduler
    rather than by simple sequential iteration.

    Args:
        effective_cfg: The effective configuration with overwrite cascade applied.
        exp_states: List of experiment states to process.
        
    Returns:
        List of experiment states after processing through the workflow.
    """
    return run_workflow_scheduler(effective_cfg, exp_states)


########### Helper function for batch execution of a single step ###########
def _run_step_batch(spec: StepSpec[Any], settings: SettingsModel, exp_states: list[ExperimentState],) -> list[ExperimentState]:
    profile = spec.profile

    logger.debug(
        "Executing %s with mode=%s workers=%s ordered=%s",
        profile.step_name,
        settings.execution,
        settings.workers,
        settings.ordered_execution,
    )

    def worker(state: ExperimentState) -> list[ExperimentState]:
        return spec.item_runner(settings, state, profile,)

    output_states: list[ExperimentState] = []

    with pbar(total=len(exp_states),
              desc=profile.step_name.capitalize(),
              logs="buffered",) as progress:
        for produced_states in execute(
            exp_states,
            worker,
            mode=settings.execution,
            workers=settings.workers,
            ordered=settings.ordered_execution,
        ):
            output_states.extend(produced_states)
            progress.advance()

    return output_states