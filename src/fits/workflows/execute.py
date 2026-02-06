

from typing import Any, Mapping
from fits.environment.state import ExperimentState
from fits.workflows.registry import REGISTRY


WORKFLOW_ORDER = [
    "convert",
]

def run_workflow(user_cfg: Mapping[str, Any], exp_state: ExperimentState) -> ExperimentState:
    
    for step_name in WORKFLOW_ORDER:
        step_spec = REGISTRY.get(step_name)
        if step_spec is None:
            continue
        
        enabled, params = user_cfg.get(step_name, (False, {}))
        if not enabled:
            continue
        
        settings = step_spec.model_validate(params)  
        
        exp_state = step_spec.runner(settings, exp_state, step_spec.step_profile, step_spec.output_name)
    
    return exp_state