from __future__ import annotations

import pytest

from fits.tasks.registration.registration_resolver import resolve_registration_plan


def test_resolve_registration_plan_uses_context_preset() -> None:
    plan = resolve_registration_plan("linear_drift")

    assert plan.mode == "time"
    assert plan.backend == "pystackreg"
    assert plan.method == "translation"


def test_resolve_registration_plan_allows_expert_overrides() -> None:
    plan = resolve_registration_plan("channel_shift", backend="pystackreg", method="affine")

    assert plan.mode == "channel"
    assert plan.backend == "pystackreg"
    assert plan.method == "affine"


def test_resolve_registration_plan_rejects_invalid_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported backend"):
        resolve_registration_plan("linear_drift", backend="bad_backend")


def test_resolve_registration_plan_rejects_invalid_method() -> None:
    with pytest.raises(ValueError, match="Unsupported method"):
        resolve_registration_plan("linear_drift", method="bad_method")
