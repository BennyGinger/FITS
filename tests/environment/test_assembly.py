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
