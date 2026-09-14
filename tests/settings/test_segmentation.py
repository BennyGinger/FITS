from __future__ import annotations

import pytest
from pydantic import ValidationError

from fits.settings.loader import resolve_step_params
from fits.settings.models import SegmentSettings


def test_per_channel_settings_are_independent() -> None:
    settings = SegmentSettings.model_validate({
        "channels": [
            {"channel": "GFP", "user_settings": {"model_type": "cyto2", "diameter": 20}},
            {"channel": "DAPI", "do_denoise": False,
             "user_settings": {"model_type": "nuclei", "diameter": 12}},
        ]
    })

    assert [entry.channel for entry in settings.channels] == ["GFP", "DAPI"]
    assert settings.channels[0].user_settings["model_type"] == "cyto2"
    assert settings.channels[1].user_settings["model_type"] == "nuclei"
    assert settings.channels[1].do_denoise is False


def test_duplicate_segmentation_targets_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Duplicate segmentation target channel"):
        SegmentSettings.model_validate({
            "channels": [{"channel": "GFP"}, {"channel": "GFP"}],
        })


def test_legacy_segmentation_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="channel_to_segment"):
        SegmentSettings.model_validate({"channel_to_segment": ["GFP"]})


def test_step_level_toml_channels_are_combined_with_shared_params() -> None:
    params = resolve_step_params("segment", {
        "params": {"overwrite": True},
        "channels": [{"channel": "GFP"}],
    })

    assert params == {"overwrite": True, "channels": [{"channel": "GFP"}]}
