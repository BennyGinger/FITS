from __future__ import annotations
from pathlib import Path
import tempfile

import pytest

from fits.environment.discovery import collect_supported_files, find_fits_outputs, discover_saved_states
from fits.environment.state import ExperimentState
from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_NAME


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


def test_find_fits_outputs_finds_expected_names_recursively(tmp_path: Path, touch) -> None:
    a = touch(tmp_path / FITS_ARRAY_NAME)
    b = touch(tmp_path / "sub" / FITS_MASK_NAME)
    touch(tmp_path / "sub" / "other.tif")

    out = find_fits_outputs(tmp_path)

    assert set(out) == {a, b}
    assert out == sorted(out)


def test_find_fits_outputs_does_not_match_similar_names(tmp_path: Path, touch) -> None:
    touch(tmp_path / (FITS_ARRAY_NAME.replace(".tif", "_copy.tif")))
    touch(tmp_path / f"copy_{FITS_MASK_NAME}")
    out = find_fits_outputs(tmp_path)
    assert out == []


def test_discover_saved_states_loads_all_valid_states() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        raw = run_dir / "a.nd2"
        raw.touch()

        s1 = (
            ExperimentState.init(run_dir / "a_s1", raw)
            .with_image(run_dir / "a_s1" / "fits_array.tif")
            .with_completed_step("convert")
        )
        s2 = (
            ExperimentState.init(run_dir / "a_s2", raw)
            .with_image(run_dir / "a_s2" / "fits_array.tif")
            .with_completed_step("convert")
        )
        s1.to_json()
        s2.to_json()

        loaded = discover_saved_states(run_dir)

        assert len(loaded) == 2
        assert {state.series_index for state in loaded} == {1, 2}
        assert {state.original_image for state in loaded} == {raw.resolve()}


def test_discover_saved_states_skips_invalid_json_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        valid_raw = run_dir / "a.nd2"
        valid_raw.touch()

        valid_state = ExperimentState.init(run_dir / "a_s1", valid_raw).with_image(run_dir / "a_s1" / "fits_array.tif")
        valid_state.to_json()

        bad_workdir = run_dir / "broken"
        bad_workdir.mkdir(parents=True, exist_ok=True)
        (bad_workdir / "experiment_state.json").write_text("{ not json", encoding="utf-8")

        caplog.set_level("WARNING")
        loaded = discover_saved_states(run_dir)

        assert len(loaded) == 1
        assert loaded[0].original_image == valid_raw.resolve()
        assert "Failed to load experiment state" in caplog.text
