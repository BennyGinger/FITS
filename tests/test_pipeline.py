from __future__ import annotations

from pathlib import Path

import pytest

from fits.workflows.experiments import ExperimentState, save_experiment_state
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
def test_pipeline_log_directory_defaults_to_run_dir_fits_logs(monkeypatch, tmp_path, log_value):
    captured = {}
    _patch_pipeline_services(monkeypatch, tmp_path, [], captured)
    cfg = _base_cfg(tmp_path)
    if log_value is not None:
        cfg["runtime"]["log_dir"] = str(tmp_path / "custom") if log_value == "custom" else log_value
    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: cfg)
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **kwargs: captured.update(kwargs))
    start_pipeline(settings_path=tmp_path / "settings.toml")
    expected_root = tmp_path / "custom" if log_value == "custom" else tmp_path
    assert captured["log_dir"] == expected_root / ".fits" / "logs"


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
    save_experiment_state(state)
    return state


def _patch_pipeline_services(monkeypatch, run_dir: Path, raw_files: list[Path], captured: dict) -> None:
    (run_dir / "settings.toml").write_text(
        f'run_dir = "{run_dir.as_posix()}"\nuser_name = "tester"\n',
        encoding="utf-8")
    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: _base_cfg(run_dir))
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **_: None)
    monkeypatch.setattr("fits.pipeline.collect_supported_files", lambda _: raw_files)
    monkeypatch.setattr("fits.pipeline.apply_overwrite_cascade", lambda cfg, order: cfg)
    monkeypatch.setattr(
        "fits.pipeline.run_batch_workflow",
        lambda _, states, **kwargs: captured.setdefault("states", states))
    monkeypatch.setattr("fits.pipeline.aggregate_quantification", lambda *args: None)
    monkeypatch.setattr("fits.pipeline.aggregate_distance_profiles", lambda *args: None)


@pytest.mark.parametrize("source_kind", ["default", "external", "saved"])
def test_pipeline_saves_input_settings_before_execution(monkeypatch, tmp_path, source_kind):
    from fits.settings.loader import load_settings
    from fits.gui.settings import SettingsAdapter

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    captured = {}
    _patch_pipeline_services(monkeypatch, run_dir, [], captured)
    destination = run_dir / ".fits" / "fits_settings.toml"
    destination.parent.mkdir()
    source = destination if source_kind == "saved" else tmp_path / "user_settings.toml"
    contents = (
        "# Preserve my settings and comments.\n"
        f'run_dir = "{run_dir.as_posix()}"\nuser_name = "tester"\n'
        '[runtime]\nexecution = "batch"\n'
        '[segment]\nenabled = true\n'
        '[[segment.channels]]\nchannel = "GFP"\n'
        '[segment.channels.user_settings]\nmodel_type = "cyto3"\ndiameter = 35\n'
    )
    if source != destination:
        destination.write_text("# Previous run settings\n", encoding="utf-8")
    source.write_text(contents, encoding="utf-8")
    monkeypatch.setattr("fits.pipeline.load_settings", load_settings)
    monkeypatch.setattr("fits.pipeline.SETTINGS_PATH", source)

    def fail_workflow(config, states, **kwargs):
        assert destination.read_text(encoding="utf-8") == contents
        raise RuntimeError("backend failed")

    monkeypatch.setattr("fits.pipeline.run_batch_workflow", fail_workflow)
    with pytest.raises(RuntimeError, match="backend failed"):
        start_pipeline(settings_path=None if source_kind == "default" else source)

    adapter = SettingsAdapter()
    adapter.load(destination)
    assert adapter.segmentation_settings().channels[0].user_settings["diameter"] == 35
    assert source.read_text(encoding="utf-8") == contents


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


@pytest.mark.parametrize("mode", ["batch", "conveyor"])
@pytest.mark.parametrize("step,title", [
    ("convert", "Conversion"), ("register_time", "Preprocessing"),
    ("segment", "Processing"), ("track", "Processing"),
])
def test_single_step_without_analysis_always_writes_report(monkeypatch, tmp_path, mode, step, title):
    from dataclasses import replace
    from fits.workflows.runtime.batch import run_batch_workflow
    from fits.workflows.runtime.scheduler import run_workflow_scheduler
    from fits.workflows.definitions.registry import REGISTRY

    captured = {}
    _patch_pipeline_services(monkeypatch, tmp_path, [], captured)
    raw = tmp_path / "input.nd2"
    raw.touch()
    state = _saved_state(tmp_path, raw, "experiment")
    cfg = _base_cfg(tmp_path)
    cfg["runtime"]["execution"] = mode
    params = {
        "convert": {}, "register_time": {},
        "segment": {"channels": [{"channel": "GFP"}]},
        "track": {"channel_to_track": ["GFP"]},
    }[step]
    cfg[step] = {"enabled": True, "params": params}
    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: cfg)
    monkeypatch.setattr("fits.pipeline.assemble_experiment_states", lambda *args: [state])
    monkeypatch.setattr("fits.pipeline.run_batch_workflow", run_batch_workflow)
    monkeypatch.setattr("fits.pipeline.run_workflow_scheduler", run_workflow_scheduler)
    monkeypatch.setitem(REGISTRY, step, replace(
        REGISTRY[step], item_runner=lambda settings, current, profile: [current]))
    logs = tmp_path / ".fits" / "logs"
    logs.mkdir(parents=True)
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **kwargs: logs / "fits_test.log")
    start_pipeline(settings_path=tmp_path / "settings.toml")
    text = (tmp_path / ".fits" / "reports" / "fits_report_test.txt").read_text()
    assert "Experiments: 1 completed" in text
    assert f"{title}: 1 completed" in text
    assert "Analysis:" not in text
    assert "Drawing:" not in text


@pytest.mark.parametrize("mode", ["batch", "conveyor"])
def test_failed_processing_writes_report_without_analysis(monkeypatch, tmp_path, mode):
    from dataclasses import replace
    from fits.workflows.runtime.batch import run_batch_workflow
    from fits.workflows.runtime.scheduler import run_workflow_scheduler
    from fits.workflows.definitions.registry import REGISTRY

    _patch_pipeline_services(monkeypatch, tmp_path, [], {})
    raw = tmp_path / "input.nd2"
    raw.touch()
    state = _saved_state(tmp_path, raw, "experiment")
    cfg = _base_cfg(tmp_path)
    cfg["runtime"]["execution"] = mode
    cfg["track"] = {"enabled": True, "params": {"channel_to_track": ["GFP"]}}
    monkeypatch.setattr("fits.pipeline.load_settings", lambda _: cfg)
    monkeypatch.setattr("fits.pipeline.assemble_experiment_states", lambda *args: [state])
    monkeypatch.setattr("fits.pipeline.run_batch_workflow", run_batch_workflow)
    monkeypatch.setattr("fits.pipeline.run_workflow_scheduler", run_workflow_scheduler)

    def fail(*args):
        raise ValueError("Tracker failed")

    monkeypatch.setitem(REGISTRY, "track", replace(REGISTRY["track"], item_runner=fail))
    logs = tmp_path / ".fits" / "logs"
    logs.mkdir(parents=True)
    monkeypatch.setattr("fits.pipeline.configure_logging", lambda **kwargs: logs / "fits_test.log")
    with pytest.raises(ValueError, match="Tracker failed"):
        start_pipeline(settings_path=tmp_path / "settings.toml")
    text = (tmp_path / ".fits" / "reports" / "fits_report_test.txt").read_text()
    assert "Processing: 0 completed / 0 partial / 0 skipped / 1 failed" in text
    assert "Tracker failed" in text
