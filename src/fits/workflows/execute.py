from __future__ import annotations

import logging
from functools import partial
from typing import Any, Mapping

from fits.environment.constant import WORKFLOW_ORDER
from fits.environment.state import ExperimentState
from fits.environment.progress import RunProgress
from fits.workflows.engines.reporting import WorkflowReporter
from fits.settings.models import SettingsModel
from fits.settings.loader import resolve_step_params
from fits.workflows.engines.executors import execute
from fits.workflows.engines.models import StepSpec
from fits.workflows.engines.registry import REGISTRY
from fits.workflows.engines.scheduler import run_workflow_scheduler
from progress_bar import pbar


logger = logging.getLogger(__name__)



def run_workflow(effective_cfg: Mapping[str, Any], exp_states: list[ExperimentState],
                 *, run_progress: RunProgress | None = None) -> list[ExperimentState]:
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
    enabled_steps = [step for step in WORKFLOW_ORDER
                     if isinstance(effective_cfg.get(step), Mapping)
                     and effective_cfg[step].get("enabled", False)]
    reporter = (WorkflowReporter(run_progress, enabled_steps, exp_states)
                if run_progress is not None else None)
    for step_name in WORKFLOW_ORDER:
        step_cfg = effective_cfg.get(step_name)

        if not isinstance(step_cfg, Mapping):
            continue

        if not step_cfg.get("enabled", False):
            continue

        spec = REGISTRY.get(step_name)

        if spec is None:
            raise ValueError(
                f"Enabled step {str(step_name)!r} is missing from the registry."
            )

        params = resolve_step_params(str(step_name), step_cfg)

        settings = spec.model_validate(params)
        exp_states = _run_step_batch(
            spec=spec,
            settings=settings,
            exp_states=exp_states,
            reporter=reporter,
        )
    
    return exp_states


def run_workflow_scheduler_entry(
    effective_cfg: Mapping[str, Any],
    exp_states: list[ExperimentState],
    *, run_progress: RunProgress | None = None,
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
    return run_workflow_scheduler(effective_cfg, exp_states, run_progress=run_progress)


########### Helper function for batch execution of a single step ###########
def _run_step_batch(spec: StepSpec[Any], settings: SettingsModel, exp_states: list[ExperimentState],
                    reporter: WorkflowReporter | None = None) -> list[ExperimentState]:
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

    if reporter is not None:
        for state in exp_states:
            reporter.started(profile.step_name, state)
        worker = partial(_reported_step, spec, settings)

    output_states: list[ExperimentState] = []
    first_error = None

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
            if reporter is not None:
                source, outputs, error = produced_states
                if error is not None:
                    reporter.failed(profile.step_name, source, error)
                    if settings.execution == "serial":
                        raise error
                    first_error = first_error or error
                    progress.advance()
                    continue
                reporter.completed(profile.step_name, source, outputs)
                produced_states = outputs
            output_states.extend(produced_states)
            progress.advance()

    if first_error is not None:
        raise first_error
    return output_states


def _reported_step(spec, settings, state):
    """Return outcomes to the parent process, which owns reporting state."""
    try:
        return state, spec.item_runner(settings, state, spec.profile), None
    except Exception as error:
        return state, [], error
