from __future__ import annotations

import pytest
from pydantic import ValidationError

from fits.settings.models import TrackSettings


def test_tracking_postprocess_defaults_to_disabled() -> None:
    settings = TrackSettings(channel_to_track=["GFP"])

    assert settings.postprocess.enabled is False
    assert settings.postprocess.shape_similarity == 0.9
    assert settings.postprocess.minimum_appearances == 5


def test_tracking_postprocess_settings_are_validated_and_recorded() -> None:
    settings = TrackSettings.model_validate({
        "channel_to_track": ["GFP"],
        "postprocess": {
            "enabled": True,
            "shape_similarity": 0.8,
            "minimum_appearances": 3,
            "extrapolate_start": False,
            "extrapolate_end": True,
        },
    })

    assert settings.postprocess.enabled is True
    assert settings.to_payload_dict()["postprocess"] == {
        "enabled": True,
        "shape_similarity": 0.8,
        "minimum_appearances": 3,
        "extrapolate_start": False,
        "extrapolate_end": True,
    }

    with pytest.raises(ValidationError):
        TrackSettings.model_validate({
            "channel_to_track": ["GFP"],
            "postprocess": {"shape_similarity": 1.1},
        })
