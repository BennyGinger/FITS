"""FIScH-owned discovery of current, compacted and legacy image/mask paths."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from pathlib import Path
from fisch.environment.paths import is_internal_path
from fisch.environment import constant as cst
from fisch.environment import naming
from fisch.workflows.experiments import discover_saved_states
from fisch.workflows.definitions.inputs import configured_profile, resolve_inputs
from fisch.settings.loader import load_settings, run_settings_path
from fisch.workflows.artifacts.provenance import read_metadata


def image_for(path: str | Path) -> Path | None:
    """
    Image for.
    """
    source = Path(path).expanduser().resolve()
    if source.is_file() and source.name in cst.IMAGE_NAMES:
        return source
    directory = source if source.is_dir() else source.parent
    if source.is_file() and source.suffix.lower() in (".tif", ".tiff"):
        try:
            refs = read_metadata(source).artifact.derived_from
            if isinstance(refs, list):
                for ref in refs:
                    candidate = (directory / ref["artifact_path"]).resolve()
                    if candidate.is_file() and candidate.name in cst.IMAGE_NAMES:
                        return candidate
        except (OSError, ValueError, KeyError):
            pass
    for name in (name for current in (*reversed(cst.IMAGE_STAGE_NAMES), cst.ARRAY_NAME) for name in naming.read_names(current)):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def first_image(directory: Path) -> Path | None:
    """
    First image.
    """
    direct = image_for(directory)
    if direct is not None:
        return direct
    folders = sorted({p.parent for name in cst.IMAGE_NAMES for p in directory.rglob(name)
                      if not is_internal_path(p, directory)})
    return image_for(folders[0]) if folders else None


def image_input_for(path: str | Path,
                    step: cst.StepName,
                    config: Mapping[str, Any] | None = None,
                    ) -> Path | None:
    """
    Resolve a tuner's input with the same StepProfile contract as execution.
    """
    # The task registry is needed for tuning, not for ordinary image viewing.
    from fisch.workflows.definitions.registry import REGISTRY
    source = Path(path).expanduser().resolve()
    directory = source if source.is_dir() else source.parent
    states = [state for state in discover_saved_states(directory.parent) if state.workdir == directory]
    if not states:
        return image_for(source)
    state = states[0]
    if state.compacted:
        raise ValueError('This experiment is compacted. Rebuild its intermediate files before tuning a processing step.')
    if config is None:
        settings = next((run_settings_path(parent) for parent in (directory, *directory.parents)
                         if run_settings_path(parent).is_file()), None)
        config = load_settings(settings) if settings else {
            name: {'enabled': name in state.completed_steps} for name in cst.WORKFLOW_ORDER}
    profile = configured_profile(REGISTRY[step].profile, config)
    return next(iter(resolve_inputs(state, profile).values()))
