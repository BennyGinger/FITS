"""Recognize run roots and resolve selections inside processed acquisitions."""

from __future__ import annotations

from pathlib import Path

from fisch.environment import constant as cst
from fisch.environment.paths import ACQUISITION_METADATA_DIR_NAME
from fisch.environment import naming


def _is_run_root(path: Path) -> bool:
    """
    Recognize a run by its saved settings or log directory.
    """
    return any((path / directory / settings).is_file() or (path / directory / 'logs').is_dir()
               for directory, settings in ((naming.RUN_METADATA, naming.SETTINGS),
                                            (naming.LEGACY_RUN_METADATA, naming.LEGACY_SETTINGS)))


def _contains_processed_files(path: Path) -> bool:
    """
    Detect experiment metadata or managed image outputs below a selection.
    """
    if (path / ACQUISITION_METADATA_DIR_NAME).is_dir() or (path / 'experiment_state.json').is_file():
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
    known = _contains_processed_files(selected) or (selected.parent / ACQUISITION_METADATA_DIR_NAME / 'experiment_state' / selected.name / 'experiment_state.json').is_file()
    if known:
        for parent in selected.parents:
            if _is_run_root(parent):
                return parent
        raise ValueError('This processed experiment is detached from its run. Choose its containing run folder (.pipeline/settings.toml or .pipeline/logs).')
    return selected
