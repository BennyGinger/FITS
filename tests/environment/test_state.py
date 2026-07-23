from datetime import datetime
from pathlib import Path
import tempfile

import pytest

from fits.environment.state import ExperimentState


def test_init_stores_original_path_relative_to_workdir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        original = workdir / "a.nd2"
        s = ExperimentState.init(workdir, original)

        assert s.original_image_rel == Path("a.nd2")
        assert s.original_image == original
        assert s.updated_at is not None


def test_init_allows_original_outside_workdir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        outside = workdir.parent / "outside.nd2"
        s = ExperimentState.init(workdir, outside)

        assert s.original_image == outside.resolve()
        assert s.original_image_rel.parts[0] == ".."


def test_with_image_sets_relative_path_only() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        s1 = ExperimentState.init(workdir, workdir / "a.nd2")
        out = workdir / "exp1" / "fits_array.tif"

        s2 = s1.with_image(out)

        assert s1 is not s2
        assert s2.image_rel == Path("exp1/fits_array.tif")
        assert s2.image == out.resolve()
        assert s2.workdir == workdir


def test_with_masks_sets_relative_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        s1 = ExperimentState.init(workdir, workdir / "a.nd2")
        masks = workdir / "exp1" / "fits_mask.tif"

        s2 = s1.with_masks(masks)

        assert s2.masks_rel == Path("exp1/fits_mask.tif")
        assert s2.masks == masks.resolve()


def test_with_completed_step_is_idempotent_and_sets_last_step() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        s = ExperimentState.init(workdir, workdir / "a.nd2")
        s = s.with_error("convert", "boom")

        s1 = s.with_completed_step("convert")
        s2 = s1.with_completed_step("convert")

        assert s1.completed_steps == ("convert",)
        assert s1.last_step == "convert"
        assert s1.last_error is None
        assert s2 == s1


def test_with_error_sets_tuple() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        s = ExperimentState.init(workdir, workdir / "a.nd2")

        s2 = s.with_error("segment", "boom")

        assert s2.last_error == ("segment", "boom")


def test_series_index_is_derived_from_workdir_suffix() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        s_ok = ExperimentState.init(root / "a_s12", root / "a.nd2")
        s_none = ExperimentState.init(root / "a_branch", root / "a.nd2")

        assert s_ok.series_index == 12
        assert s_none.series_index is None


def test_workdir_relative_returns_relative_when_possible() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        workdir = run_dir / "a_s1"
        s = ExperimentState.init(workdir, run_dir / "a.nd2")

        assert s.workdir_relative(run_dir) == Path("a_s1")
        assert s.workdir_relative(None) == workdir


def test_to_relative_and_absolute_helpers_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        target = workdir / "nested" / "result.tif"
        rel = ExperimentState._to_relative(workdir, target)

        s = ExperimentState.init(workdir, workdir / "a.nd2")
        back = s._to_absolute(rel)

        assert rel == Path("nested/result.tif")
        assert back == target.resolve()


def test_to_relative_accepts_outside_paths() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        outside = workdir.parent / "external.tif"

        rel = ExperimentState._to_relative(workdir, outside)

        assert rel.parts[0] == ".."


def test_to_json_roundtrip_and_alias_methods() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        image = workdir / "exp1" / "fits_array.tif"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.touch()

        s = ExperimentState.init(workdir, workdir / "a.nd2")
        s = s.with_image(image).with_completed_step("convert")

        out_state = s.save()
        saved_path = workdir / "experiment_state.json"

        assert out_state == s
        assert saved_path.exists()

        loaded = ExperimentState.load(workdir)
        assert loaded == s
        assert isinstance(loaded.original_image_rel, Path)
        assert isinstance(loaded.updated_at, datetime)


def test_from_json_raises_on_invalid_field_type() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        json_path = workdir / "experiment_state.json"
        json_path.write_text(
            """
{
  "original_image_rel": 10,
  "image_rel": null,
  "masks_rel": null,
  "completed_steps": [],
  "last_error": null,
  "updated_at": null
}
""".strip(),
            encoding="utf-8",
        )

        with pytest.raises(TypeError, match="original_image_rel must be a string path"):
            ExperimentState._from_json(workdir)


def test_to_json_atomic_cleanup_when_replace_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        image = workdir / "exp1" / "fits_array.tif"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.touch()

        state = ExperimentState.init(workdir, workdir / "a.nd2").with_image(image)
        target = workdir / "experiment_state.json"

        def fail_replace(_src: Path, _dst: Path) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr("fits.environment.state.os.replace", fail_replace)

        with pytest.raises(OSError, match="replace failed"):
            state._to_json()

        leftovers = list(workdir.glob(".experiment_state.json.*.tmp"))
        assert leftovers == []
        assert not target.exists()
