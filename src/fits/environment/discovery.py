from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
import logging

from pathlib import Path
from fits_io import SUPPORTED_EXTENSIONS

from fits.environment.constant import StepName
from fits.environment.state import ExperimentState
from fits.environment.constant import EXCLUDED_PREFIXES
from fits.workflows.metadata.models import FitsMeta


logger = logging.getLogger(__name__)


def collect_supported_files(directory: Path) -> list[Path]:
    """
    Collect all supported image files under a directory.

    Returns:
        Sorted list of image file paths.
    """
    prefixes = tuple(EXCLUDED_PREFIXES)
    exts = {e.lower() for e in SUPPORTED_EXTENSIONS}
    
    supported_files: set[Path] = set()
    for p in directory.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith(prefixes):
            continue
        if p.suffix.lower() in exts:
            supported_files.add(p)
            logger.debug(f"Found supported file: {p}")
    
    return sorted(supported_files)


def assemble_experiment_states(run_dir: Path,
                               raw_files: Sequence[Path],
                               workflow_cfg: Mapping[str, Any],
                               user_name: str
                               ) -> list[ExperimentState]:
    """
    Build the experiment states for a pipeline run.

    Saved states are ignored when the enabled convert step is configured to
    overwrite, because conversion must then restart from the raw input files.

    Otherwise, saved states are retained and raw states are created only for
    original images that are not already represented by a saved state.
    """
    raw_states = [
        ExperimentState.init(raw_file.parent, 
                             raw_file, 
                             fits_meta=FitsMeta.init(user_name=user_name))
        for raw_file in raw_files]

    if _convert_overwrites(workflow_cfg):
        return raw_states

    saved_states = discover_saved_states(run_dir)

    converted_originals = {
        state.original_image
        for state in saved_states
    }

    remaining_raw_states = [
        state
        for state in raw_states
        if state.original_image not in converted_originals
    ]

    return saved_states + remaining_raw_states


def discover_saved_states(run_dir: Path) -> list[ExperimentState]:
    """
    Discover and load all saved ``experiment_state.json`` files under ``run_dir``.

    Invalid state files are skipped with a warning.
    """
    states: list[ExperimentState] = []
    for json_path in run_dir.rglob("experiment_state.json"):
        workdir = json_path.parent
        try:
            states.append(ExperimentState.load_state(workdir))
        except Exception as exc:
            logger.warning("Failed to load experiment state at %s: %s", json_path, exc)
            continue
    return states


def _convert_overwrites(workflow_cfg: Mapping[str, Any]) -> bool:
    """
    Return whether the enabled convert step overwrites existing outputs.
    """
    step_cfg = workflow_cfg.get(StepName.CONVERT)

    if not isinstance(step_cfg, Mapping):
        return False

    if not step_cfg.get("enabled", False):
        return False

    params = step_cfg.get("params")

    if not isinstance(params, Mapping):
        return False

    return bool(params.get("overwrite", False))



if __name__ == "__main__":
    
    
    for tag in SUPPORTED_EXTENSIONS:
        print(tag)