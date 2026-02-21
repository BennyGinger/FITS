from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from fits.environment.state import ExperimentState
from fits.pipeline import start_pipeline


def _base_cfg(run_dir: Path) -> dict:
    return {
        "run_dir": str(run_dir),
        "user_name": "tester",
        "runtime": {
            "mode": "cli",
            "dry_run": False,
            "console_level": "info",
            "file_level": "debug",
        },
    }


def _saved_state(run_dir: Path, raw_path: Path, workdir_name: str, series_index: int) -> ExperimentState:
    state = (
        ExperimentState.init(run_dir, raw_path)
        .with_image(run_dir / workdir_name / "fits_array.tif")
        .commit(series_index=series_index, experiment_id=f"{raw_path.stem}-s{series_index}")
    )
    state.to_json()
    return state


def test_start_pipeline_states_one_raw_no_saved(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path
    raw = run_dir / "a.nd2"
    raw.touch()

    captured: dict[str, list[ExperimentState]] = {}

    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: _base_cfg(run_dir))
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **_: None)
    monkeypatch.setattr("fits.pipeline.coerce_mode", lambda _: "cli")
    monkeypatch.setattr("fits.pipeline.use_ctx", lambda _: nullcontext())
    monkeypatch.setattr("fits.pipeline.collect_supported_files", lambda _: [raw])
    monkeypatch.setattr("fits.pipeline.run_workflow", lambda _, states: captured.setdefault("states", states))

    start_pipeline(settings_path=run_dir / "settings.toml")

    states = captured["states"]
    assert len(states) == 1
    assert states[0].original_image_rel == Path("a.nd2")
    assert states[0].series_index == 0


def test_start_pipeline_states_raw_with_two_series_saved(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path
    raw = run_dir / "a.nd2"
    raw.touch()

    saved0 = _saved_state(run_dir, raw, "a_s0", 0)
    saved1 = _saved_state(run_dir, raw, "a_s1", 1)

    captured: dict[str, list[ExperimentState]] = {}

    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: _base_cfg(run_dir))
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **_: None)
    monkeypatch.setattr("fits.pipeline.coerce_mode", lambda _: "cli")
    monkeypatch.setattr("fits.pipeline.use_ctx", lambda _: nullcontext())
    monkeypatch.setattr("fits.pipeline.collect_supported_files", lambda _: [raw])
    monkeypatch.setattr("fits.pipeline.run_workflow", lambda _, states: captured.setdefault("states", states))

    start_pipeline(settings_path=run_dir / "settings.toml")

    states = captured["states"]
    assert len(states) == 2
    assert all(state.original_image_rel == Path("a.nd2") for state in states)
    assert {state.series_index for state in states} == {0, 1}
    assert {state.experiment_id for state in states} == {saved0.experiment_id, saved1.experiment_id}


def test_start_pipeline_states_two_raw_only_one_converted(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path
    converted_raw = run_dir / "a.nd2"
    new_raw = run_dir / "b.nd2"
    converted_raw.touch()
    new_raw.touch()

    saved = _saved_state(run_dir, converted_raw, "a_s0", 0)

    captured: dict[str, list[ExperimentState]] = {}

    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: _base_cfg(run_dir))
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **_: None)
    monkeypatch.setattr("fits.pipeline.coerce_mode", lambda _: "cli")
    monkeypatch.setattr("fits.pipeline.use_ctx", lambda _: nullcontext())
    monkeypatch.setattr("fits.pipeline.collect_supported_files", lambda _: [converted_raw, new_raw])
    monkeypatch.setattr("fits.pipeline.run_workflow", lambda _, states: captured.setdefault("states", states))

    start_pipeline(settings_path=run_dir / "settings.toml")

    states = captured["states"]
    assert len(states) == 2
    assert states[0].original_image_rel == Path("a.nd2")
    assert states[0].experiment_id == saved.experiment_id
    assert states[1].original_image_rel == Path("b.nd2")
    assert states[1].experiment_id is None
