from dataclasses import replace
from datetime import datetime
from pathlib import Path
import tempfile

import pytest

from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_NAME
from fits.environment.state import ExperimentState, _discover_saved_states, assemble_experiment_states


def test_init_stores_original_path_relative_to_run_dir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        original = run_dir / "a.nd2"
        s = ExperimentState.init(run_dir, original)

        assert s.original_image_rel == Path("a.nd2")
        assert s.original_image == original
        assert s.updated_at is not None


def test_init_raises_for_original_outside_run_dir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        outside = Path("/tmp/outside.nd2")

        with pytest.raises(ValueError, match="is not under run_dir"):
            ExperimentState.init(run_dir, outside)


def test_with_image_sets_relative_and_workdir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s1 = ExperimentState.init(run_dir, run_dir / "a.nd2")
        out = run_dir / "exp1" / "fits_array.tif"

        s2 = s1.with_image(out, last_step="convert")

        assert s1 is not s2
        assert s2.image_rel == Path("exp1/fits_array.tif")
        assert s2.image == out
        assert s2.workdir == out.parent
        assert s2.last_step == "convert"


def test_with_masks_sets_relative_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s1 = ExperimentState.init(run_dir, run_dir / "a.nd2")
        masks = run_dir / "exp1" / "fits_mask.tif"

        s2 = s1.with_masks(masks)

        assert s2.masks_rel == Path("exp1/fits_mask.tif")
        assert s2.masks == masks


def test_with_settings_hash_updates_one_step() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s1 = ExperimentState.init(run_dir, run_dir / "a.nd2")

        s2 = s1.with_settings_hash("convert", "h1")

        assert s1.step_settings_hash == {}
        assert s2.step_settings_hash == {"convert": "h1"}


def test_mark_running_done_failed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")

        s = s.mark_running("step_a")
        assert s.step_status["step_a"] == "running"

        s = s.mark_done("step_a")
        assert s.step_status["step_a"] == "done"

        s = s.mark_failed("step_b", ValueError("boom"))
        assert s.step_status["step_b"] == "failed"
        assert s.last_error == "boom"


def test_commit_updates_timestamp() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        before = s.updated_at

        s2 = s.commit(last_step="x")

        assert s2.last_step == "x"
        assert isinstance(s2.updated_at, datetime)
        assert before is None or s2.updated_at >= before


def test_needs_run_true_when_overwrite() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")

        assert s.needs_run("convert", settings_hash="h1", overwrite=True)


def test_needs_run_true_when_step_not_done() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")

        assert s.needs_run("convert", settings_hash="h1", overwrite=False)


def test_needs_run_true_when_hash_changed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        image = run_dir / "fits_array.tif"
        image.touch()

        s = s.with_image(image).with_settings_hash("convert", "old").mark_done("convert")

        assert s.needs_run("convert", settings_hash="new", overwrite=False)


def test_needs_run_true_when_required_image_missing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        missing = run_dir / "fits_array.tif"
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        s = s.with_image(missing).with_settings_hash("convert", "h1").mark_done("convert")

        assert s.needs_run("convert", settings_hash="h1", overwrite=False, required_output=FITS_ARRAY_NAME)


def test_needs_run_true_when_required_masks_missing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        missing = run_dir / "fits_mask.tif"
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        s = s.with_masks(missing).with_settings_hash("segment", "h1").mark_done("segment")

        assert s.needs_run("segment", settings_hash="h1", overwrite=False, required_output=FITS_MASK_NAME)


def test_needs_run_true_when_sidecar_missing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image = run_dir / "fits_array.tif"
        image.touch()

        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        s = s.with_image(image).with_settings_hash("convert", "h1").mark_done("convert")

        assert s.needs_run(
            "convert",
            settings_hash="h1",
            overwrite=False,
            required_files_rel=(Path("sidecars/meta.json"),),
        )


def test_needs_run_false_when_all_conditions_satisfied() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image = run_dir / "fits_array.tif"
        image.touch()
        sidecar = run_dir / "sidecars" / "meta.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.touch()

        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        s = s.with_image(image).with_settings_hash("convert", "h1").mark_done("convert")

        assert not s.needs_run(
            "convert",
            settings_hash="h1",
            overwrite=False,
            required_output=FITS_ARRAY_NAME,
            required_files_rel=(Path("sidecars/meta.json"),),
        )


def test_to_relative_and_absolute_helpers_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        original = run_dir / "nested" / "result.tif"
        rel = ExperimentState._to_relative(run_dir, original)

        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        back = s._to_absolute(rel)

        assert rel == Path("nested/result.tif")
        assert back == original


def test_to_relative_raises_when_outside_run_dir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)

        with pytest.raises(ValueError, match="is not under run_dir"):
            ExperimentState._to_relative(run_dir, Path("/tmp/external.tif"))


def test_to_absolute_returns_absolute_as_is() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        absolute = Path("/tmp/file.tif")

        assert s._to_absolute(absolute) == absolute


def test_to_json_uses_workdir_default_name_and_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image = run_dir / "exp1" / "fits_array.tif"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.touch()

        s = ExperimentState.init(run_dir, run_dir / "a.nd2")
        s = (
            s.with_image(image, last_step="convert")
            .with_settings_hash("convert", "hash1")
            .mark_done("convert")
            .commit(experiment_id="exp-01")
        )

        out_state = s.to_json()
        saved_path = image.parent / "experiment_state.json"

        assert out_state == s
        assert saved_path.exists()

        loaded = ExperimentState.from_json(image.parent)
        assert loaded == s
        assert isinstance(loaded.run_dir, Path)
        assert isinstance(loaded.original_image_rel, Path)
        assert isinstance(loaded.updated_at, datetime)


def test_to_json_raises_when_workdir_missing_and_no_path_given() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        s = ExperimentState.init(run_dir, run_dir / "a.nd2")

        with pytest.raises(ValueError, match="workdir is not available"):
            s.to_json()


def test_from_json_raises_on_invalid_field_type() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        json_path = workdir / "experiment_state.json"
        json_path.write_text(
            """
{
  "run_dir": "/tmp/run",
  "original_image_rel": "a.nd2",
  "image_rel": null,
  "masks_rel": null,
  "last_step": null,
  "experiment_id": null,
  "series_index": "0",
  "step_status": {},
  "step_settings_hash": {},
  "last_error": null,
  "updated_at": null
}
""".strip(),
            encoding="utf-8",
        )

        with pytest.raises(TypeError, match="series_index must be an integer"):
            ExperimentState.from_json(workdir)


def test_discover_saved_states_loads_all_valid_states() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        raw = run_dir / "a.nd2"
        raw.touch()

        s1 = ExperimentState.init(run_dir, raw).with_image(run_dir / "a_s1" / "fits_array.tif").commit(series_index=0)
        s2 = ExperimentState.init(run_dir, raw).with_image(run_dir / "a_s2" / "fits_array.tif").commit(series_index=1)
        s1.to_json()
        s2.to_json()

        loaded = _discover_saved_states(run_dir)

        assert len(loaded) == 2
        assert {state.series_index for state in loaded} == {0, 1}
        assert {state.original_image_rel for state in loaded} == {Path("a.nd2")}


def test_discover_saved_states_skips_invalid_json_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        valid_raw = run_dir / "a.nd2"
        valid_raw.touch()

        valid_state = ExperimentState.init(run_dir, valid_raw).with_image(run_dir / "a_s1" / "fits_array.tif")
        valid_state.to_json()

        bad_workdir = run_dir / "broken"
        bad_workdir.mkdir(parents=True, exist_ok=True)
        (bad_workdir / "experiment_state.json").write_text("{ not json", encoding="utf-8")

        caplog.set_level("WARNING")
        loaded = _discover_saved_states(run_dir)

        assert len(loaded) == 1
        assert loaded[0].original_image_rel == Path("a.nd2")
        assert "Failed to load experiment state" in caplog.text


def test_assemble_experiment_states_merges_saved_with_only_new_raws() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        converted_raw = run_dir / "a.nd2"
        new_raw = run_dir / "b.nd2"
        converted_raw.touch()
        new_raw.touch()

        saved0 = (
            ExperimentState.init(run_dir, converted_raw)
            .with_image(run_dir / "a_s0" / "fits_array.tif")
            .commit(series_index=0, experiment_id="a-s0")
        )
        saved1 = (
            ExperimentState.init(run_dir, converted_raw)
            .with_image(run_dir / "a_s1" / "fits_array.tif")
            .commit(series_index=1, experiment_id="a-s1")
        )
        saved0.to_json()
        saved1.to_json()

        states = assemble_experiment_states(run_dir, [converted_raw, new_raw])

        assert len(states) == 3
        assert [state.original_image_rel for state in states].count(Path("a.nd2")) == 2
        assert Path("b.nd2") in {state.original_image_rel for state in states}
        assert {state.experiment_id for state in states if state.original_image_rel == Path("a.nd2")} == {"a-s0", "a-s1"}
        b_state = next(state for state in states if state.original_image_rel == Path("b.nd2"))
        assert b_state.experiment_id is None


def test_to_json_atomic_cleanup_when_replace_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image = run_dir / "exp1" / "fits_array.tif"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.touch()

        state = ExperimentState.init(run_dir, run_dir / "a.nd2").with_image(image)
        target = image.parent / "experiment_state.json"

        def fail_replace(_src: Path, _dst: Path) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr("fits.environment.state.os.replace", fail_replace)

        with pytest.raises(OSError, match="replace failed"):
            state.to_json()

        leftovers = list(image.parent.glob(".experiment_state.json.*.tmp"))
        assert leftovers == []
        assert not target.exists()
