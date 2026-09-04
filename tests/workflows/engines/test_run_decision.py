from pathlib import Path

from fits.environment.constant import StepName
from fits.environment.state import ExperimentState
from fits.workflows.engines.registry import REGISTRY
from fits.workflows.engines.run_decision import RunDecision, decide_run


def _state_with_image(tmp_path: Path, *, completed: bool = False) -> ExperimentState:
    raw = tmp_path / "raw.nd2"
    image = tmp_path / "fits_array.tif"
    raw.touch()
    image.touch()
    step = StepName.CONVERT if completed else StepName.REGISTER_TIME
    return ExperimentState.init(tmp_path, raw).with_complete_step(
        step_name=step,
        artifact_kind="image",
        artifact_path=image,
    )


def test_decide_run_whole_step_overwrite_never_skips(tmp_path: Path) -> None:
    state = _state_with_image(tmp_path, completed=True)

    decision = decide_run(state, REGISTRY[StepName.CONVERT].profile, overwrite=True)

    assert decision == RunDecision(requested_items=[0], completed_items=[], pending_items=[0])
    assert not decision.is_complete


def test_decide_run_whole_step_skips_existing_completed_artifact(tmp_path: Path) -> None:
    state = _state_with_image(tmp_path, completed=True)

    decision = decide_run(state, REGISTRY[StepName.CONVERT].profile, overwrite=False)

    assert decision == RunDecision(requested_items=[0], completed_items=[0], pending_items=[])
    assert decision.is_complete


def test_decide_run_whole_step_repeats_when_artifact_is_missing(tmp_path: Path) -> None:
    state = _state_with_image(tmp_path, completed=True)
    state.artifact("image").unlink()

    decision = decide_run(state, REGISTRY[StepName.CONVERT].profile, overwrite=False)

    assert decision.pending_items == [0]


def test_decide_run_channels_all_pending_without_metadata(tmp_path: Path) -> None:
    state = _state_with_image(tmp_path)

    decision = decide_run(
        state, REGISTRY[StepName.SEGMENT].profile, overwrite=False, requested_items=[1, 2]
    )

    assert decision == RunDecision(requested_items=[1, 2], completed_items=[], pending_items=[1, 2])


def test_decide_run_channels_uses_state_metadata(tmp_path: Path) -> None:
    state = _state_with_image(tmp_path).with_metadata(
        step_name=StepName.SEGMENT,
        created_by="cellpose-kit",
        exported_channel=[1],
        channels_params={"model": "cpsam"},
    )

    decision = decide_run(
        state, REGISTRY[StepName.SEGMENT].profile, overwrite=False, requested_items=[1, 2]
    )

    assert decision == RunDecision(requested_items=[1, 2], completed_items=[1], pending_items=[2])


def test_decide_run_channel_overwrite_forces_all_pending(tmp_path: Path) -> None:
    state = _state_with_image(tmp_path).with_metadata(
        step_name=StepName.SEGMENT,
        created_by="cellpose-kit",
        exported_channel=[1, 2],
        channels_params={},
    )

    decision = decide_run(
        state, REGISTRY[StepName.SEGMENT].profile, overwrite=True, requested_items=[1, 2]
    )

    assert decision == RunDecision(requested_items=[1, 2], completed_items=[], pending_items=[1, 2])
