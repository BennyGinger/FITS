from __future__ import annotations

from pathlib import Path

import pytest

from fits.environment.state import ExperimentState
from fits.pipeline import start_pipeline


def _base_cfg(run_dir: Path) -> dict:
    return {
        "run_dir": str(run_dir),
        "user_name": "tester",
        "runtime": {
            "execution": "batch",
            "console_level": "info",
            "file_level": "debug",
        },
    }


@pytest.mark.parametrize("log_value", [None, "", "   ", "custom"])
def test_pipeline_log_directory_defaults_to_run_dir_logs(monkeypatch, tmp_path, log_value):
    captured = {}
    _patch_pipeline_services(monkeypatch, tmp_path, [], captured)
    cfg = _base_cfg(tmp_path)
    if log_value is not None:
        cfg["runtime"]["log_dir"] = str(tmp_path / "custom") if log_value == "custom" else log_value
    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: cfg)
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **kwargs: captured.update(kwargs))
    start_pipeline(settings_path=tmp_path / "settings.toml")
    expected_root = tmp_path / "custom" if log_value == "custom" else tmp_path
    assert captured["log_dir"] == expected_root / "logs"


def _saved_state(run_dir: Path, raw_path: Path, workdir_name: str) -> ExperimentState:
    workdir = run_dir / workdir_name
    image = workdir / "fits_array.tif"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.touch()
    state = ExperimentState.init(workdir, raw_path).with_complete_step(
        step_name="convert",
        artifact_kind="image",
        artifact_path=image,
    )
    state.save_state()
    return state


def _patch_pipeline_services(monkeypatch, run_dir: Path, raw_files: list[Path], captured: dict) -> None:
    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: _base_cfg(run_dir))
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **_: None)
    monkeypatch.setattr("fits.pipeline.collect_supported_files", lambda _: raw_files)
    monkeypatch.setattr("fits.pipeline.apply_overwrite_cascade", lambda cfg, order: cfg)
    monkeypatch.setattr("fits.pipeline.run_workflow", lambda _, states: captured.setdefault("states", states))
    monkeypatch.setattr("fits.pipeline.aggregate_quantification", lambda *args: None)
    monkeypatch.setattr("fits.pipeline.aggregate_distance_profiles", lambda *args: None)


def test_start_pipeline_states_one_raw_no_saved(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path
    raw = run_dir / "a.nd2"
    raw.touch()

    captured: dict[str, list[ExperimentState]] = {}

    _patch_pipeline_services(monkeypatch, run_dir, [raw], captured)

    start_pipeline(settings_path=run_dir / "settings.toml")

    states = captured["states"]
    assert len(states) == 1
    assert states[0].artifacts["raw_image"] == Path("a.nd2")


def test_start_pipeline_states_raw_with_two_series_saved(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path
    raw = run_dir / "a.nd2"
    raw.touch()

    saved0 = _saved_state(run_dir, raw, "a_s0")
    saved1 = _saved_state(run_dir, raw, "a_s1")

    captured: dict[str, list[ExperimentState]] = {}

    _patch_pipeline_services(monkeypatch, run_dir, [raw], captured)

    start_pipeline(settings_path=run_dir / "settings.toml")

    states = captured["states"]
    assert len(states) == 2
    assert all(state.original_image == raw.resolve() for state in states)
    assert {state.workdir.name for state in states} == {"a_s0", "a_s1"}
    assert {state.experiment_id for state in states} == {saved0.experiment_id, saved1.experiment_id}


def test_start_pipeline_states_two_raw_only_one_converted(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path
    converted_raw = run_dir / "a.nd2"
    new_raw = run_dir / "b.nd2"
    converted_raw.touch()
    new_raw.touch()

    saved = _saved_state(run_dir, converted_raw, "a_s0")

    captured: dict[str, list[ExperimentState]] = {}

    _patch_pipeline_services(monkeypatch, run_dir, [converted_raw, new_raw], captured)

    start_pipeline(settings_path=run_dir / "settings.toml")

    states = captured["states"]
    assert len(states) == 2
    assert states[0].original_image == converted_raw.resolve()
    assert states[0].experiment_id == saved.experiment_id
    assert states[1].original_image == new_raw.resolve()
    assert states[1].workdir == run_dir
