"""Durable storage and discovery of experiment states."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from fits.workflows.experiments.model import ExperimentState
from fits.environment.paths import EXPERIMENT_DIR_NAME, STATE_DIR_NAME, STATE_FILENAME, INTERNAL_DIR_NAMES, experiment_state_path, ensure_fits_directory
from fits.workflows.experiments.serialization import deserialize_experiment_state, serialize_experiment_state


logger = logging.getLogger(__name__)


def save_experiment_state(state: ExperimentState) -> ExperimentState:
    """
    Atomically save an experiment state in its work directory.
    """
    root = state.original_image.parent
    target_path = experiment_state_path(state.workdir, acquisition=root)
    ensure_fits_directory(target_path.parent)
    data = serialize_experiment_state(state)
    data["series_path"] = Path(os.path.relpath(state.workdir, root)).as_posix()
    payload = json.dumps(data, indent=2)
    descriptor, temp_path_string = tempfile.mkstemp(dir=target_path.parent,
                                                    prefix=f".{target_path.name}.",
                                                    suffix=".tmp",
                                                    text=True,
                                                    )
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


def load_experiment_state(workdir: Path, *, run_dir: Path | None = None) -> ExperimentState:
    """
    Load an experiment state using the supplied work directory as authoritative.
    """
    json_path = experiment_state_path(workdir)
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    return ExperimentState(workdir=workdir, run_dir=run_dir, **deserialize_experiment_state(raw))


def discover_saved_states(run_dir: Path) -> list[ExperimentState]:
    """
    Load valid experiment-state files found recursively under a run directory.
    """
    states: list[ExperimentState] = []
    pattern = f"**/{EXPERIMENT_DIR_NAME}/{STATE_DIR_NAME}/*/{STATE_FILENAME}"
    for json_path in run_dir.glob(pattern):
        try:
            root = json_path.parents[3]
            if any(part in INTERNAL_DIR_NAMES for part in root.relative_to(run_dir).parts):
                continue
            raw = json.loads(json_path.read_text(encoding='utf-8'))
            relative = Path(raw['series_path'])
            workdir = (root / relative).resolve()
            relative_workdir = workdir.relative_to(root.resolve())
            if any(part in INTERNAL_DIR_NAMES for part in relative_workdir.parts):
                continue
            states.append(ExperimentState(workdir=workdir,
                                          run_dir=run_dir,
                                          **deserialize_experiment_state(raw),
                                          ))
        except Exception as exc:
            logger.warning("Failed to load experiment state at %s: %s", json_path, exc)
    return states
