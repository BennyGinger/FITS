from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fisch.environment.constant import RegistrationAlgorithm, RegistrationContext, RegistrationMethod, RegistrationMode


@dataclass(frozen=True)
class RegistrationPlan:
    mode: RegistrationMode
    algorithm: RegistrationAlgorithm
    method: RegistrationMethod


_PRESET_PLANS: dict[RegistrationContext, RegistrationPlan] = {
    "linear_drift": RegistrationPlan(mode="time", algorithm="pystackreg", method="translation"),
    "rotational_drift": RegistrationPlan(mode="time", algorithm="pystackreg", method="rigid_body"),
    "complex_drift": RegistrationPlan(mode="time", algorithm="pystackreg", method="affine"),
    "channel_shift": RegistrationPlan(mode="channel", algorithm="cv2", method="translation"),
    "channel_shift_dual_cam": RegistrationPlan(mode="channel", algorithm="cv2", method="rigid_body"),
    "channel_shift_complex": RegistrationPlan(mode="channel", algorithm="cv2", method="affine"),
}

_VALID_ALGORITHMS: set[str] = {"scikit", "pystackreg", "cv2"}
_VALID_METHODS: set[str] = {"translation", "rigid_body", "affine"}


def resolve_registration_plan(context: RegistrationContext,
                              algorithm: str | None = None,
                              method: str | None = None,
                              ) -> RegistrationPlan:
    """
    Resolve the registration plan for a given context, optionally overriding the algorithm and method.

    Args:
        context: The registration context to resolve.
        algorithm: Optional algorithm to override the preset.
        method: Optional method to override the preset.

    Returns:
        The resolved RegistrationPlan.
    """
    preset = _PRESET_PLANS[context]
    final_algorithm = preset.algorithm if algorithm is None else algorithm
    final_method = preset.method if method is None else method
    if final_algorithm not in _VALID_ALGORITHMS:
        raise ValueError(f"Unsupported algorithm '{final_algorithm}'. Supported: {sorted(_VALID_ALGORITHMS)}.")
    if final_method not in _VALID_METHODS:
        raise ValueError(f"Unsupported method '{final_method}'. Supported: {sorted(_VALID_METHODS)}.")
    return RegistrationPlan(mode=preset.mode,
                            algorithm=cast(RegistrationAlgorithm, final_algorithm),
                            method=cast(RegistrationMethod, final_method),
                            )
