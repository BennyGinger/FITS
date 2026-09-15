"""Orchestrate workflows that complete each step for the full batch."""

from collections.abc import Mapping
from typing import Any

from fits.environment.constant import WORKFLOW_ORDER
from fits.workflows.runtime.progress import RunProgress
from fits.workflows.experiments import ExperimentState
from fits.settings.loader import resolve_step_params
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.runtime.batch.execution import execute_batch_step
from fits.workflows.runtime.progress.reporting import WorkflowReporter


def run_batch_workflow(effective_cfg: Mapping[str, Any],
                        exp_states: list[ExperimentState],
                        *,
                        run_progress: RunProgress | None = None,
                        ) -> list[ExperimentState]:
    """
    Run every enabled workflow step across the entire experiment batch.
    """
    enabled_steps = [step_name
                    for step_name in WORKFLOW_ORDER
                    if isinstance(effective_cfg.get(step_name), Mapping)
                    and effective_cfg[step_name].get("enabled", False)]
    reporter = (WorkflowReporter(run_progress, enabled_steps, exp_states)
                if run_progress is not None
                else None)

    for step_name in enabled_steps:
        spec = REGISTRY.get(step_name)
        if spec is None:
            raise ValueError(f"Enabled step {str(step_name)!r} is missing from the registry.")
        
        step_cfg = effective_cfg[step_name]
        params = resolve_step_params(str(step_name), step_cfg)
        settings = spec.model_validate(params)
        exp_states = execute_batch_step(spec=spec,
                                        settings=settings,
                                        exp_states=exp_states,
                                        reporter=reporter,)

    return exp_states
