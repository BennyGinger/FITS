"""Validated compartment settings exposed by FITS quantification."""

import pytest
from pydantic import ValidationError

from fits.settings.models import ExtractSettings


@pytest.mark.parametrize("field, value", [
    ("membrane_thickness", 0), ("membrane_thickness", -1),
    ("membrane_thickness", float("inf")), ("membrane_thickness", float("nan")),
    ("dilation_radius", -1), ("dilation_radius", float("inf")),
    ("dilation_radius", float("nan")),
])
def test_invalid_compartment_distances_are_rejected(field: str, value: float) -> None:
    """
    Validate radii even while compartment extraction is disabled.
    """
    with pytest.raises(ValidationError, match=field):
        ExtractSettings.model_validate({field: value})


def test_compartment_settings_round_trip_and_default_to_full_only() -> None:
    """
    Preserve explicit compartment settings in saved workflow parameters.
    """
    assert ExtractSettings().compartments is False
    settings = ExtractSettings(compartments=True, membrane_thickness=2.5, dilation_radius=0)
    assert ExtractSettings.model_validate(settings.model_dump()) == settings
    assert settings.model_dump()["membrane_thickness"] == 2.5
