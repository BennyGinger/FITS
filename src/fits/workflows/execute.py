from typing import Any, Mapping
from fits.environment.state import ExperimentState
from fits.workflows.registry import REGISTRY


WORKFLOW_ORDER = [
    "convert",
]

def run_workflow(user_cfg: Mapping[str, Any], exp_states: list[ExperimentState]) -> list[ExperimentState]:
    
    for step_name in WORKFLOW_ORDER:
        step_spec = REGISTRY.get(step_name)
        if step_spec is None:
            continue
        
        step_cfg = user_cfg.get(step_name) or {}
        enabled = step_cfg.get("enabled", False)
        params = step_cfg.get("params", {})
        
        if not enabled:
            continue
        
        settings = step_spec.model_validate(params)  
        
        exp_states = step_spec.runner(settings, exp_states, step_spec.step_profile, step_spec.output_name)
    
    return exp_states