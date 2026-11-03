"""FITS-owned grouping of original acquisitions and their series."""

from __future__ import annotations
from pathlib import Path
from fits.environment.paths import EXPERIMENT_DIR_NAME, ensure_fits_directory


def group_acquisition(source: Path) -> Path:
    """
    Group acquisition.
    """
    source = source.expanduser().resolve()
    if (source.parent / EXPERIMENT_DIR_NAME).is_dir():
        return source
    target = source.parent / source.stem
    if target.exists():
        raise ValueError(f'Acquisition destination already exists: {target}. Use Manage files to review its structure.')
    target.mkdir()
    moved = target / source.name
    try:
        source.replace(moved)
        ensure_fits_directory(target / EXPERIMENT_DIR_NAME)
    except Exception:
        if moved.exists() and not source.exists():
            moved.replace(source)
        if not any(target.iterdir()):
            target.rmdir()
        raise
    return moved
