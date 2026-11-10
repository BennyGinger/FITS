"""FIScH-owned grouping of original acquisitions and their series."""

from __future__ import annotations
import logging
from pathlib import Path
from fisch.environment.paths import ACQUISITION_METADATA_DIR_NAME, ensure_metadata_directory


def group_acquisition(source: Path, target: Path | None = None) -> Path:
    """
    Move the original into its planned acquisition folder while preserving its filename.
    """
    source = source.expanduser().resolve()
    if (source.parent / ACQUISITION_METADATA_DIR_NAME).is_dir():
        return source
    target = target if target is not None else source.parent / source.stem
    if target.exists():
        raise ValueError(f'Acquisition destination already exists: {target}. Use Manage files to review its structure.')
    target.mkdir()
    moved = target / source.name
    try:
        source.replace(moved)
        ensure_metadata_directory(target / ACQUISITION_METADATA_DIR_NAME)
    except Exception:
        if moved.exists() and not source.exists():
            moved.replace(source)
        if not any(target.iterdir()):
            target.rmdir()
        raise
    if target.name != source.stem:
        logging.getLogger(__name__).info("Duplicate acquisition stem: %s grouped in %s", source.name, target)
    return moved
