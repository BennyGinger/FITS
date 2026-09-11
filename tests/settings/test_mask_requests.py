import pytest
from pydantic import ValidationError

from fits.settings.models import DistanceProfileSettings, ExtractSettings


def test_mask_request_defaults():
    extraction = ExtractSettings()
    profile = DistanceProfileSettings()
    assert extraction.draw_ref_mask is False
    assert extraction.expected_ref_masks == 1
    assert profile.draw_ref_mask is True
    assert profile.expected_ref_masks == 1
    assert profile.draw_roi_mask is False
    assert profile.expected_roi_masks == 1


@pytest.mark.parametrize('payload', [
    {'draw_ref_mask': False}, {'expected_ref_masks': 0}, {'expected_ref_masks': -1},
])
def test_profile_requires_reference_requests(payload):
    with pytest.raises(ValidationError):
        DistanceProfileSettings(**payload)


def test_optional_roi_allows_zero_target():
    assert DistanceProfileSettings(expected_roi_masks=0).expected_roi_masks == 0


def test_drawing_settings_survive_serialization():
    settings = ExtractSettings(draw_ref_mask=True, expected_ref_masks=3)
    assert ExtractSettings.model_validate(settings.model_dump()) == settings
