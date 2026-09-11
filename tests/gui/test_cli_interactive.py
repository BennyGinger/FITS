from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fits.cli.interactive import run_pipeline_cli


def test_cli_supplies_interactive_mask_bridge(tmp_path: Path, monkeypatch) -> None:
    captured = {}
    settings = tmp_path / "settings.toml"
    settings.touch()
    monkeypatch.setattr(
        "fits.cli.interactive.load_settings",
        lambda _: {"run_dir": str(tmp_path)},
    )

    def fake_start_pipeline(*, settings_path, mask_interaction, run_progress):
        captured["settings_path"] = settings_path
        captured["interaction"] = mask_interaction
        captured["progress"] = run_progress
        mask_interaction.input_complete()

    monkeypatch.setattr(
        "fits.cli.interactive.start_pipeline", fake_start_pipeline)

    run_pipeline_cli(settings)

    assert captured["settings_path"] == settings.resolve()
    assert captured["interaction"] is not None
    assert captured["progress"] is not None
