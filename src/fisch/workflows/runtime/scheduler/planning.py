from __future__ import annotations

from collections.abc import Sequence, Mapping
from dataclasses import dataclass, replace
from typing import Any
from fisch.environment.constant import WORKFLOW_ORDER
from fisch.settings.loader import resolve_step_params
from fisch.workflows.definitions.models import StepSpec
from fisch.workflows.definitions.registry import REGISTRY
from fisch.workflows.definitions.inputs import configured_profile


@dataclass(frozen=True, slots=True)
class RuntimeStep:
    """
    Pair a registered step specification with its validated settings.
    """
    spec: StepSpec[Any]
    settings: Any


def resolve_runtime_steps(workflow_cfg: Mapping[str, Any],
                          *,
                          registry: Mapping[str, StepSpec[Any]] | None = None,
                          workflow_order: Sequence[str] | None = None,
                          ) -> list[RuntimeStep]:
    """
    Resolve enabled registry entries and validate their settings.
    """
    runtime_steps: list[RuntimeStep] = []
    registry = REGISTRY if registry is None else registry
    for step_name in WORKFLOW_ORDER if workflow_order is None else workflow_order:
        step_cfg = workflow_cfg.get(step_name)

        if not isinstance(step_cfg, Mapping) or not step_cfg.get("enabled", False):
            continue

        spec = registry.get(step_name)
        if spec is None:
            raise ValueError(f"Enabled step {str(step_name)!r} is missing from the registry.")

        params = resolve_step_params(str(step_name), step_cfg)
        spec = replace(spec, profile=configured_profile(spec.profile, workflow_cfg))
        runtime_steps.append(RuntimeStep(spec=spec, settings=spec.model_validate(params)))
    return runtime_steps
