from pathlib import Path

from fits.environment.constant import StepName
from fits.workflows.experiments import ExperimentState


def test_init_stores_raw_artifact_relative_to_workdir(tmp_path: Path) -> None:
    original = tmp_path / "a.nd2"
    state = ExperimentState.init(tmp_path, original)

    assert state.artifacts["raw_image"] == Path("a.nd2")
    assert state.original_image == original
    assert state.updated_at is not None


def test_init_allows_original_outside_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "branch"
    outside = tmp_path / "outside.nd2"
    state = ExperimentState.init(workdir, outside)

    assert state.original_image == outside.resolve()
    assert state.artifacts["raw_image"].parts[0] == ".."


def test_with_complete_step_sets_artifact_and_is_immutable(tmp_path: Path) -> None:
    state = ExperimentState.init(tmp_path, tmp_path / "a.nd2")
    output = tmp_path / "nested" / "fits_array.tif"

    updated = state.with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind="image",
        artifact_path=output,
    )

    assert updated is not state
    assert "image" not in state.artifacts
    assert updated.artifacts["image"] == Path("nested/fits_array.tif")
    assert updated.artifact("image") == output.resolve()
    assert updated.completed_steps == (StepName.CONVERT,)
    assert updated.last_step == StepName.CONVERT


def test_with_complete_step_is_idempotent_for_completion_name(tmp_path: Path) -> None:
    state = ExperimentState.init(tmp_path, tmp_path / "a.nd2")
    first = state.with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind="image",
        artifact_path=tmp_path / "first.tif",
    )
    second = first.with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind="image",
        artifact_path=tmp_path / "second.tif",
    )

    assert second.completed_steps == (StepName.CONVERT,)
    assert second.artifact("image") == (tmp_path / "second.tif").resolve()


def test_with_complete_step_can_move_branch_workdir(tmp_path: Path) -> None:
    state = ExperimentState.init(tmp_path, tmp_path / "a.nd2")
    branch = tmp_path / "a_s1"
    output = branch / "fits_array.tif"

    updated = state.with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind="image",
        artifact_path=output,
        workdir=branch,
    )

    assert updated.workdir == branch
    assert updated.original_image == (tmp_path / "a.nd2").resolve()
    assert updated.artifacts["image"] == Path("fits_array.tif")


def test_workdir_relative_returns_relative_when_possible(tmp_path: Path) -> None:
    workdir = tmp_path / "a_s1"
    state = ExperimentState.init(workdir, tmp_path / "a.nd2")

    assert state.workdir_relative(tmp_path) == Path("a_s1")
    assert state.workdir_relative(None) == workdir


def test_path_helpers_roundtrip_and_accept_outside_paths(tmp_path: Path) -> None:
    workdir = tmp_path / "branch"
    target = workdir / "nested" / "result.tif"
    outside = tmp_path / "external.tif"
    state = ExperimentState.init(workdir, tmp_path / "a.nd2")

    relative = ExperimentState._to_relative(workdir, target)
    assert relative == Path("nested/result.tif")
    assert state._to_absolute(relative) == target.resolve()
    assert ExperimentState._to_relative(workdir, outside).parts[0] == ".."

