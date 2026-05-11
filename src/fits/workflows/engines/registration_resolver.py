from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fits.environment.constant import RegistrationBackend, RegistrationContext, RegistrationMethod, RegistrationMode


@dataclass(frozen=True)
class RegistrationPlan:
    mode: RegistrationMode
    backend: RegistrationBackend
    method: RegistrationMethod


_PRESET_PLANS: dict[RegistrationContext, RegistrationPlan] = {
    "linear_drift": RegistrationPlan(mode="time", backend="pystackreg", method="translation"),
    "rotational_drift": RegistrationPlan(mode="time", backend="pystackreg", method="rigid_body"),
    "complex_drift": RegistrationPlan(mode="time", backend="pystackreg", method="affine"),
    "channel_shift": RegistrationPlan(mode="channel", backend="cv2", method="translation"),
    "channel_shift_dual_cam": RegistrationPlan(mode="channel", backend="cv2", method="rigid_body"),
    "channel_shift_complex": RegistrationPlan(mode="channel", backend="cv2", method="affine"),
}

_VALID_BACKENDS: set[str] = {"scikit", "pystackreg", "cv2"}
_VALID_METHODS: set[str] = {"translation", "rigid_body", "affine"}


def resolve_registration_plan(context: RegistrationContext, backend: str | None = None, method: str | None = None) -> RegistrationPlan:
    preset = _PRESET_PLANS[context]
    final_backend = preset.backend if backend is None else backend
    final_method = preset.method if method is None else method
    if final_backend not in _VALID_BACKENDS:
        raise ValueError(f"Unsupported backend '{final_backend}'. Supported: {sorted(_VALID_BACKENDS)}.")
    if final_method not in _VALID_METHODS:
        raise ValueError(f"Unsupported method '{final_method}'. Supported: {sorted(_VALID_METHODS)}.")
    return RegistrationPlan(mode=preset.mode, backend=cast(RegistrationBackend, final_backend), method=cast(RegistrationMethod, final_method))
