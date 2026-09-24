from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fits.environment.constant import WORKFLOW_ORDER
from fits.settings.loader import resolve_step_params
from fits.workflows.definitions.models import StepSpec
from fits.workflows.definitions.registry import REGISTRY


@dataclass(frozen=True, slots=True)
class RuntimeStep:
    """
    Pair a registered step specification with its validated settings.
    """
    spec: StepSpec[Any]
    settings: Any


def resolve_runtime_steps(workflow_cfg: Mapping[str, Any]) -> list[RuntimeStep]:
    """
    Resolve enabled registry entries and validate their settings.
    """
    runtime_steps: list[RuntimeStep] = []
    for step_name in WORKFLOW_ORDER:
        step_cfg = workflow_cfg.get(step_name)
        
        if not isinstance(step_cfg, Mapping) or not step_cfg.get("enabled", False):
            continue
        
        spec = REGISTRY.get(step_name)
        if spec is None:
            raise ValueError(f"Enabled step {str(step_name)!r} is missing from the registry.")
        
        params = resolve_step_params(str(step_name), step_cfg)
        runtime_steps.append(RuntimeStep(spec=spec, settings=spec.model_validate(params)))
    return runtime_steps
