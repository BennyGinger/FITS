from fits.workflows.registry import REGISTRY
from fits.environment.constant import STEP_CONVERT, DIST_IO
from fits.workflows.provenance import StepProfile


def test_registry_keys_match_stepspec_name() -> None:
    for key, spec in REGISTRY.items():
        assert key == spec.name

def test_registry_step_profile_is_correct() -> None:
    spec = REGISTRY[STEP_CONVERT]
    assert spec.step_profile == StepProfile(distribution=DIST_IO, step_name=STEP_CONVERT)

def test_registry_settings_model_validates() -> None:
    spec = REGISTRY[STEP_CONVERT]
    out = spec.model_validate({"overwrite": True})  # minimal valid payload for ConvertSettings
    assert out.overwrite is True

def test_registry_runner_is_callable() -> None:
    for spec in REGISTRY.values():
        assert callable(spec.runner)
