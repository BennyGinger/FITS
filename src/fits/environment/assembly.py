from collections.abc import Sequence
from pathlib import Path

from fits.environment.discovery import discover_saved_states
from fits.environment.state import ExperimentState


def assemble_experiment_states(run_dir: Path, raw_files: Sequence[Path]) -> list[ExperimentState]:
    """
    Build the final experiment state list for a run.

    Keeps all discovered saved states and appends only raw-file states whose
    ``original_image_rel`` is not already represented by saved states.
    """
    raw_states = [ExperimentState.init(run_dir, raw_file) for raw_file in raw_files]
    saved_states = discover_saved_states(run_dir)

    converted_originals = {state.original_image_rel for state in saved_states}
    remaining_raw_states = [
        state for state in raw_states
        if state.original_image_rel not in converted_originals
    ]
    return saved_states + remaining_raw_states