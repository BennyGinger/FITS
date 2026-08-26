from collections.abc import Mapping
from pathlib import Path

from fits.environment.constant import WORKFLOW_ORDER
from fits.settings.loader import load_settings
from fits.workflows.engines.registry import REGISTRY


TEMPLATE_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "fits"
    / "settings"
    / "template_settings.toml"
)


def test_template_contains_and_validates_every_registered_step() -> None:
    config = load_settings(TEMPLATE_PATH)

    assert set(REGISTRY) == set(WORKFLOW_ORDER)

    for step_name in WORKFLOW_ORDER:
        spec = REGISTRY[step_name]
        step_config = config.get(step_name)
        assert isinstance(step_config, Mapping), f"Missing [{step_name}] table"
        assert isinstance(step_config.get("enabled"), bool)

        params = step_config.get("params")
        assert isinstance(params, Mapping), f"Missing [{step_name}.params] table"
        settings = spec.model_validate(params)
        assert "execution" in params
        assert "workers" in params
        assert "ordered_execution" not in params
        assert settings.workers == spec.settings_model.model_fields["workers"].default
