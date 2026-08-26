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
    assert adapter.validate_for_run() == []


def test_overwrite_is_basic_for_every_step() -> None:
    for layout in STEP_LAYOUTS.values():
        assert "overwrite" in layout.basic
        assert "overwrite" not in layout.advanced
