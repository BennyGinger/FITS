from __future__ import annotations

import pytest
from pydantic import ValidationError

from fisch.settings.loader import resolve_step_params
from fisch.settings.models import SegmentChannelSettings, SegmentSettings


def test_segmentation_has_no_implicit_target_channel() -> None:
    assert SegmentSettings().channels == []
    with pytest.raises(ValidationError, match="Field required"):
        SegmentChannelSettings.model_validate({})


@pytest.mark.parametrize("channel", ["", "   "])
def test_blank_segmentation_target_is_rejected(channel) -> None:
    with pytest.raises(ValidationError, match="Segmentation channel cannot be empty"):
        SegmentChannelSettings(channel=channel)


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


@pytest.mark.parametrize("threshold", [0, 0.5, 1])
def test_stitch_threshold_accepts_overlap_boundaries(threshold: float) -> None:
    """
    Allow disabled stitching and the complete range of valid overlap scores.
    """
    settings = SegmentSettings.model_validate({
        "channels": [{"channel": "GFP", "user_settings": {"stitch_threshold": threshold}}],
    })
    assert settings.channels[0].user_settings["stitch_threshold"] == threshold


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_stitch_threshold_rejects_invalid_overlap_scores(threshold: float) -> None:
    """
    Reject invalid TOML or API values before invoking Cellpose.
    """
    with pytest.raises(ValidationError, match="stitch_threshold must be between 0 and 1"):
        SegmentSettings.model_validate({
            "channels": [{"channel": "GFP", "user_settings": {"stitch_threshold": threshold}}],
        })


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
