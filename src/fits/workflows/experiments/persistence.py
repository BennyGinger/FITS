"""Durable storage and discovery of experiment states."""

import json
import logging
import os
from pathlib import Path
import tempfile

from fits.workflows.experiments.model import ExperimentState
from fits.workflows.experiments.serialization import (
    deserialize_experiment_state, serialize_experiment_state)


logger = logging.getLogger(__name__)
STATE_FILENAME = "experiment_state.json"


def save_experiment_state(state: ExperimentState) -> ExperimentState:
    """
    Atomically save an experiment state in its work directory.
    """
    target_path = state.workdir / STATE_FILENAME
    target_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(serialize_experiment_state(state), indent=2)
    descriptor, temp_path_string = tempfile.mkstemp(dir=target_path.parent,
                                                    prefix=f".{target_path.name}.",
                                                    suffix=".tmp",
                                                    text=True,)
    temp_path = Path(temp_path_string)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target_path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return state


def load_experiment_state(workdir: Path) -> ExperimentState:
    """
    Load an experiment state using the supplied work directory as authoritative.
    """
    json_path = workdir / STATE_FILENAME
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    return ExperimentState(workdir=workdir, **deserialize_experiment_state(raw))


def discover_saved_states(run_dir: Path) -> list[ExperimentState]:
    """
    Load valid experiment-state files found recursively under a run directory.
    """
    states: list[ExperimentState] = []
    for json_path in run_dir.rglob(STATE_FILENAME):
        try:
            states.append(load_experiment_state(json_path.parent))
        except Exception as exc:
            logger.warning("Failed to load experiment state at %s: %s", json_path, exc)
    return states
