"""Recognize run roots and resolve selections inside processed acquisitions."""

from __future__ import annotations

from pathlib import Path

from fits.environment import constant as cst
from fits.environment.paths import EXPERIMENT_DIR_NAME


def _is_run_root(path: Path) -> bool:
    """
    Recognize a run by its saved settings or log directory.
    """
    return (path / '.fits/fits_settings.toml').is_file() or (path / '.fits/logs').is_dir()


def _contains_processed_files(path: Path) -> bool:
    """
    Detect experiment metadata or managed image outputs below a selection.
    """
    if (path / EXPERIMENT_DIR_NAME).is_dir() or (path / 'experiment_state.json').is_file():
        return True
    return any(next(path.rglob(name), None) is not None for name in cst.IMAGE_NAMES + cst.MASK_NAMES)


def resolve_run_root(selected: Path) -> Path:
    """
    Promote a processed experiment selection to its containing run directory.
    """
    selected = selected.expanduser().resolve()
    if _is_run_root(selected):
        return selected
    # Walk upward first for known acquisition/series folders; a parent metadata
    # directory also identifies a series whose artifact files have been removed.
    known = _contains_processed_files(selected) or (selected.parent / EXPERIMENT_DIR_NAME / 'experiment_state' / selected.name / 'experiment_state.json').is_file()
    if known:
        for parent in selected.parents:
            if _is_run_root(parent):
                return parent
        raise ValueError('This processed experiment is detached from its run. Choose its containing run folder (.fits/fits_settings.toml or .fits/logs).')
    return selected
