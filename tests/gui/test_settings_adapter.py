from pathlib import Path

import tomllib

from fits.environment.constant import StepName
from fits.gui.settings_adapter import SAVED_SETTINGS_NAME, STEP_LAYOUTS, SettingsAdapter


def test_adapter_updates_and_saves_comment_preserving_copy(tmp_path: Path) -> None:
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "Test user"
    adapter.set_step_enabled(StepName.SEGMENT, True)
    adapter.set_field_value(StepName.SEGMENT, "channel_to_segment", ["GFP"])

    destination = adapter.save_to_run_dir()

    assert destination == tmp_path / SAVED_SETTINGS_NAME
    saved_text = destination.read_text(encoding="utf-8")
    assert "# FITS settings template." in saved_text
    assert "# Internal ordering control; not exposed in the GUI." in saved_text
    assert "# Required when segmentation is enabled." in saved_text

    saved = tomllib.loads(saved_text)
    assert saved["run_dir"] == str(tmp_path)
    assert saved["user_name"] == "Test user"
    assert saved["segment"]["enabled"] is True
    assert saved["segment"]["params"]["channel_to_segment"] == ["GFP"]


def test_adapter_load_fills_fields_missing_from_older_settings(tmp_path: Path) -> None:
    settings_path = tmp_path / "old_settings.toml"
    settings_path.write_text(
        'user_name = "User"\nrun_dir = "/tmp"\n\n[convert]\nenabled = true\n'
        "\n[convert.params]\noverwrite = true\n",
        encoding="utf-8",
    )

    adapter = SettingsAdapter()
    adapter.load(settings_path)

    assert adapter.field_value(StepName.CONVERT, "z_projection") == "max"
    assert adapter.field_value(StepName.SEGMENT, "channel_to_segment") == []
    assert adapter.validate_steps() == {}


def test_run_validation_requires_identity_and_existing_directory(tmp_path: Path) -> None:
    adapter = SettingsAdapter()
    assert "Select a run directory." in adapter.validate_for_run()
    assert "Enter a user name." in adapter.validate_for_run()

    adapter.run_dir = str(tmp_path)
    adapter.user_name = "User"
    assert adapter.validate_for_run() == [
        "Convert: Enter at least one channel label (channel_labels)."
    ]

    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    assert adapter.validate_for_run() == []


def test_missing_user_fields_only_checks_enabled_steps() -> None:
    adapter = SettingsAdapter()

    assert adapter.missing_user_fields() == [
        "Convert: Enter at least one channel label (channel_labels)."
    ]

    adapter.set_step_enabled(StepName.REGISTER_CHANNEL, True)
    adapter.set_step_enabled(StepName.SEGMENT, True)
    adapter.set_step_enabled(StepName.TRACK, True)
    assert adapter.missing_user_fields() == [
        "Convert: Enter at least one channel label (channel_labels).",
        "Register channels: Choose a reference channel (reference_channel).",
        "Segmentation: Choose at least one channel to segment (channel_to_segment).",
        "Tracking: Choose at least one channel to track (channel_to_track).",
    ]

    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    adapter.set_field_value(StepName.REGISTER_CHANNEL, "reference_channel", "GFP")
    adapter.set_field_value(StepName.SEGMENT, "channel_to_segment", ["GFP"])
    adapter.set_field_value(StepName.TRACK, "channel_to_track", ["GFP"])
    assert adapter.missing_user_fields() == []

    adapter.set_field_value(StepName.TRACK, "channel_to_track", [])
    adapter.set_step_enabled(StepName.TRACK, False)
    assert adapter.missing_user_fields() == []


def test_overwrite_is_basic_for_every_step() -> None:
    for layout in STEP_LAYOUTS.values():
        assert "overwrite" in layout.basic
        assert "overwrite" not in layout.advanced


def test_mask_request_settings_round_trip(tmp_path: Path) -> None:
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_field_value(StepName.EXTRACT, "draw_ref_mask", True)
    adapter.set_field_value(StepName.EXTRACT, "expected_ref_masks", 3)
    adapter.set_field_value(StepName.DISTANCE_PROFILE, "draw_roi_mask", True)
    adapter.set_field_value(StepName.DISTANCE_PROFILE, "expected_roi_masks", 2)
    path = adapter.save_to_run_dir()
    reloaded = SettingsAdapter()
    reloaded.load(path)
    assert reloaded.field_value(StepName.EXTRACT, "draw_ref_mask") is True
    assert reloaded.field_value(StepName.EXTRACT, "expected_ref_masks") == 3
    from fits.settings.models import DistanceProfileSettings
    params = reloaded.document[StepName.DISTANCE_PROFILE]["params"].unwrap()
    assert "draw_ref_mask" not in params
    assert DistanceProfileSettings.model_validate(params).draw_ref_mask is True
    assert reloaded.field_value(StepName.DISTANCE_PROFILE, "expected_roi_masks") == 2
    assert "draw_ref_mask" not in STEP_LAYOUTS[StepName.DISTANCE_PROFILE].basic
