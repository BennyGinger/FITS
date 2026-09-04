from __future__ import annotations
from pathlib import Path
import tempfile

import pytest

from fits.environment.discovery import collect_supported_files, discover_saved_states
from fits.environment.state import ExperimentState
from fits.environment.constant import StepName


def _saved_state(workdir: Path, raw: Path) -> ExperimentState:
    image = workdir / "fits_array.tif"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.touch()
    state = ExperimentState.init(workdir, raw).with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind="image",
        artifact_path=image,
    )
    state.save_state()
    return state


def test_collect_supported_files_recursive_and_filters(tmp_path: Path, touch) -> None:
    # supported
    a = touch(tmp_path / "a.tif")
    b = touch(tmp_path / "sub" / "b.nd2")
    c = touch(tmp_path / "deep" / "more" / "c.tiff")

    # excluded prefix
    touch(tmp_path / "fits_skip.tif")
    touch(tmp_path / "sub" / "fits_skip2.nd2")

    # unsupported files
    touch(tmp_path / "notes.csv")
    touch(tmp_path / "sub" / "report.pdf")

    out = collect_supported_files(tmp_path)

    assert set(out) == {a, b, c}
    assert out == sorted(out)


def test_collect_supported_files_extension_is_case_insensitive(tmp_path: Path, touch) -> None:
    a = touch(tmp_path / "A.TIF")
    b = touch(tmp_path / "B.TiF")
    out = collect_supported_files(tmp_path)
    assert set(out) == {a, b}


def test_discover_saved_states_loads_all_valid_states() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        raw = run_dir / "a.nd2"
        raw.touch()

        s1 = _saved_state(run_dir / "a_s1", raw)
        s2 = _saved_state(run_dir / "a_s2", raw)

        loaded = discover_saved_states(run_dir)

        assert len(loaded) == 2
        assert {state.workdir.name for state in loaded} == {"a_s1", "a_s2"}
        assert {state.original_image for state in loaded} == {raw.resolve()}


def test_discover_saved_states_skips_invalid_json_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        valid_raw = run_dir / "a.nd2"
        valid_raw.touch()

        _saved_state(run_dir / "a_s1", valid_raw)

        bad_workdir = run_dir / "broken"
        bad_workdir.mkdir(parents=True, exist_ok=True)
        (bad_workdir / "experiment_state.json").write_text("{ not json", encoding="utf-8")

        caplog.set_level("WARNING")
        loaded = discover_saved_states(run_dir)

        assert len(loaded) == 1
        assert loaded[0].original_image == valid_raw.resolve()
        assert "Failed to load experiment state" in caplog.text
