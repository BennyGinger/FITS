import copy
from typing import Any, Mapping, Sequence
import logging

from fits.environment.constant import STEP_CONVERT, STEP_SEGMENT
from fits.environment.state import ExperimentState
from fits.workflows.engines.registry import REGISTRY
from fits.workflows.engines.scheduler import run_workflow_scheduler


logger = logging.getLogger(__name__)

WORKFLOW_ORDER = [
    STEP_CONVERT,
    STEP_SEGMENT,
]


def resolve_effective_workflow_cfg(user_cfg: Mapping[str, Any], workflow_order: Sequence[str]) -> dict[str, Any]:
    resolved: dict[str, Any] = copy.deepcopy(dict(user_cfg))
    cascade = False

    for step_name in workflow_order:
        step_cfg = resolved.get(step_name)
        if not isinstance(step_cfg, dict):
            continue
        if not step_cfg.get("enabled", False):
            continue

        params = step_cfg.get("params")
        if not isinstance(params, dict):
            params = {}
            step_cfg["params"] = params

        overwrite = bool(params.get("overwrite", False))
        if cascade and not overwrite:
            params["overwrite"] = True

        if bool(params.get("overwrite", False)):
            cascade = True

    return resolved


def first_effective_overwrite_step(effective_cfg: Mapping[str, Any], workflow_order: Sequence[str]) -> str | None:
    for step_name in workflow_order:
        step_cfg = effective_cfg.get(step_name)
        if not isinstance(step_cfg, dict):
            continue
        if not step_cfg.get("enabled", False):
            continue

        params = step_cfg.get("params")
        if not isinstance(params, dict):
            continue
        if bool(params.get("overwrite", False)):
            return step_name
    return None

def run_workflow(user_cfg: Mapping[str, Any], exp_states: list[ExperimentState]) -> list[ExperimentState]:
    effective_cfg = resolve_effective_workflow_cfg(user_cfg, WORKFLOW_ORDER)
    
    for step_name in WORKFLOW_ORDER:
        step_spec = REGISTRY.get(step_name)
        if step_spec is None:
            continue
        
        step_cfg = effective_cfg.get(step_name) or {}
        enabled = step_cfg.get("enabled", False)
        params = step_cfg.get("params", {})
        
        if not enabled:
            continue
        
        settings = step_spec.model_validate(params)
        logger.debug(f"Running step '{step_name}' with settings: {settings}")

        exp_states = step_spec.runner(settings, exp_states, step_spec.step_profile, step_spec.output_name)
    
    return exp_states


def run_workflow_scheduler_entry(
    workflow_cfg: Mapping[str, Any],
    exp_states: list[ExperimentState],
) -> list[ExperimentState]:
    return run_workflow_scheduler(workflow_cfg, exp_states)