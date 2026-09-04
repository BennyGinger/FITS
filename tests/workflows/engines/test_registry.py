from fits.environment.constant import DIST_IO, StepName
from fits.settings.models import ConvertSettings
from fits.workflows.engines.registry import REGISTRY


def test_registry_profiles_match_their_keys() -> None:
    for key, spec in REGISTRY.items():
        assert key == spec.profile.step_name


def test_convert_registry_entry_is_complete() -> None:
    spec = REGISTRY[StepName.CONVERT]
    assert spec.profile.distribution == DIST_IO
    assert spec.settings_model is ConvertSettings
    assert callable(spec.item_runner)
    assert spec.pool == "cpu"


def test_registry_settings_models_validate() -> None:
    settings = REGISTRY[StepName.CONVERT].model_validate({"overwrite": True})
    assert settings.overwrite is True
