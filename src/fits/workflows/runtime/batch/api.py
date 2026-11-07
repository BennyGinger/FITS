"""Orchestrate workflows that complete each step for the full batch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from fits.environment.constant import WORKFLOW_ORDER
from fits.workflows.runtime.progress import RunProgress
from fits.workflows.experiments import ExperimentState, active_states
from fits.settings.loader import resolve_step_params
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.runtime.batch.execution import execute_batch_step
from fits.workflows.runtime.progress.reporting import WorkflowReporter
from fits.workflows.definitions.models import require_automatic_specs
from fits.workflows.runtime.scheduler.planning import resolve_runtime_steps


def run_batch_workflow(effective_cfg: Mapping[str, Any],
                       exp_states: list[ExperimentState],
                       *,
                       run_progress: RunProgress | None = None,
                       terminal_progress: bool = True,
                       ) -> list[ExperimentState]:
    """
    Run every enabled workflow step across the entire experiment batch.
    """
    exp_states = active_states(exp_states)
    steps = resolve_runtime_steps(effective_cfg, registry=REGISTRY, workflow_order=WORKFLOW_ORDER)
    resolved_steps = [(step.spec, step.settings) for step in steps]
    enabled_steps = [step.spec.profile.step_name for step in steps]
    require_automatic_specs(spec for spec, _ in resolved_steps)
    reporter = (WorkflowReporter(run_progress, enabled_steps, exp_states)
                if run_progress is not None
                else None)

    for spec, settings in resolved_steps:
        exp_states = execute_batch_step(spec=spec,
                                        settings=settings,
                                        exp_states=exp_states,
                                        reporter=reporter,
                                        terminal_progress=terminal_progress,
                                        )

    return exp_states
