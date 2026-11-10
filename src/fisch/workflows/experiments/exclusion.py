"""Shared experiment inclusion and folder-selection rules."""

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from fisch.workflows.experiments.model import ExperimentState
from fisch.workflows.experiments.persistence import discover_saved_states, save_experiment_state


def active_states(states: Iterable[ExperimentState]) -> list[ExperimentState]:
    """
    Return active experiments while leaving discovery available for inspection.
    """
    return [state for state in states if state.excluded is not True]


def active_raw_files(files: Iterable[Path], states: Iterable[ExperimentState]) -> list[Path]:
    """
    Omit acquisitions whose already converted series are all excluded.
    """
    known = list(states)
    excluded_origins = {state.original_image for state in known if state.excluded}
    active_origins = {state.original_image for state in active_states(known)}
    return [path for path in files if path not in excluded_origins - active_origins]


def selected_experiments(states: Iterable[ExperimentState], folders: Iterable[Path]) -> list[ExperimentState]:
    """
    Select each converted experiment beneath the selected folders once.
    """
    selected = set(folders)
    return [state for state in states
            if 'convert' in state.completed_steps
            and any(state.workdir == folder or folder in state.workdir.parents for folder in selected)]


def set_excluded(root: Path, folders: Iterable[Path], excluded: bool) -> None:
    """
    Persist one inclusion choice under the shared writer lock.
    """
    # The channel-label package imports task registration; keep that dependency
    # out of experiment discovery's module initialization.
    from fisch.channel_labels.lock import run_write_guard

    with run_write_guard(root):
        states = selected_experiments(discover_saved_states(root), folders)
        if any(state.migration_checkpoint is not None for state in states):
            raise ValueError('Fully rebuild migrated experiments before changing their inclusion.')
        for state in states:
            if state.excluded != excluded:
                save_experiment_state(replace(state, excluded=excluded))
