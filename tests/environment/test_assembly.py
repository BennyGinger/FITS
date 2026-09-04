from __future__ import annotations
from pathlib import Path
import tempfile

from fits.environment.discovery import assemble_experiment_states
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


def test_assemble_experiment_states_merges_saved_with_only_new_raws() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        converted_raw = run_dir / "a.nd2"
        new_raw = run_dir / "b.nd2"
        converted_raw.touch()
        new_raw.touch()

        saved0 = _saved_state(run_dir / "a_s0", converted_raw)
        saved1 = _saved_state(run_dir / "a_s1", converted_raw)

        states = assemble_experiment_states(
            run_dir, [converted_raw, new_raw], {}, "tester")

        assert len(states) == 3
        assert [state.original_image for state in states].count(converted_raw.resolve()) == 2
        assert new_raw.resolve() in {state.original_image for state in states}
        assert {state.experiment_id for state in states if state.original_image == converted_raw.resolve()} == {
            saved0.experiment_id,
            saved1.experiment_id,
        }
        b_state = next(state for state in states if state.original_image == new_raw.resolve())
        assert b_state.workdir == run_dir
