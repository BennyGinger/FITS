from __future__ import annotations
from pathlib import Path
import tempfile

from fits.environment.assembly import assemble_experiment_states
from fits.environment.state import ExperimentState


def test_assemble_experiment_states_merges_saved_with_only_new_raws() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        converted_raw = run_dir / "a.nd2"
        new_raw = run_dir / "b.nd2"
        converted_raw.touch()
        new_raw.touch()

        saved0 = (
            ExperimentState.init(run_dir / "a_s0", converted_raw)
            .with_image(run_dir / "a_s0" / "fits_array.tif")
            .with_completed_step("convert")
        )
        saved1 = (
            ExperimentState.init(run_dir / "a_s1", converted_raw)
            .with_image(run_dir / "a_s1" / "fits_array.tif")
            .with_completed_step("convert")
        )
        saved0._to_json()
        saved1._to_json()

        states = assemble_experiment_states(run_dir, [converted_raw, new_raw])

        assert len(states) == 3
        assert [state.original_image for state in states].count(converted_raw.resolve()) == 2
        assert new_raw.resolve() in {state.original_image for state in states}
        assert {state.experiment_id for state in states if state.original_image == converted_raw.resolve()} == {
            saved0.experiment_id,
            saved1.experiment_id,
        }
        b_state = next(state for state in states if state.original_image == new_raw.resolve())
        assert b_state.workdir == run_dir
