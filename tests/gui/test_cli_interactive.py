from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from typer.testing import CliRunner

from fits.cli.interactive import run_pipeline_cli
from fits.cli.main import app


runner = CliRunner()


def test_run_command_accepts_a_settings_file(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "settings.toml"
    settings.touch()
    captured: list[Path] = []
    monkeypatch.setattr("fits.cli.main.run_pipeline_cli", captured.append)

    result = runner.invoke(app, ["run", str(settings)])

    assert result.exit_code == 0
    assert captured == [settings.resolve()]


def test_run_command_rejects_a_missing_settings_file(tmp_path: Path) -> None:
    settings = tmp_path / "missing.toml"

    result = runner.invoke(app, ["run", str(settings)])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_cli_supplies_interactive_mask_bridge(tmp_path: Path, monkeypatch) -> None:
    captured = {}
    settings = tmp_path / "settings.toml"
    settings.touch()
    monkeypatch.setattr(
        "fits.cli.interactive.load_settings",
        lambda _: {"run_dir": str(tmp_path)},
    )

    def fake_start_pipeline(*, settings_path, interaction, run_progress):
        captured["settings_path"] = settings_path
        captured["interaction"] = interaction
        captured["progress"] = run_progress
        interaction.mask_input_complete()

    monkeypatch.setattr(
        "fits.cli.interactive.start_pipeline", fake_start_pipeline)

    run_pipeline_cli(settings)

    assert captured["settings_path"] == settings.resolve()
    assert captured["interaction"] is not None
    assert captured["progress"] is not None
