from typing import Any

from fits.environment.state import ExperimentState
from fits.workflows.provenance import StepProfile


def should_skip_step(exp_state: ExperimentState, step_name: str, overwrite: bool) -> bool:
    """
    Generic skip predicate for workflow steps based on experiment state and overwrite policy.
    """
    if overwrite:
        return False
    return (step_name in exp_state.completed_steps
            and exp_state.image is not None
            and exp_state.image.exists())

def build_fits_payload(step_profile: StepProfile, **kwargs) -> dict[str, Any]:
    """
    Builds payloads for FITS workflow steps, ensuring consistent provenance information. Any other keyword arguments can be included as needed for specific steps, which will then be included in the provenance info.
    """
    provenance_info: dict[str, Any] = step_profile.dump()
    provenance_info.update(**kwargs)
    return provenance_info