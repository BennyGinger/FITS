"""Paths for FITS-owned run metadata."""

from __future__ import annotations

from pathlib import Path
from fits.environment.hidden import hide_on_windows
import hashlib
import tempfile


FITS_DIR_NAME = ".fits"
LOGS_DIR_NAME = "logs"
REPORTS_DIR_NAME = "reports"


def fits_dir(root: Path) -> Path:
    """
    Return the FITS metadata directory below a run or override root.
    """
    directory = root.expanduser().resolve() / FITS_DIR_NAME
    hide_on_windows(directory)
    return directory


def ensure_fits_directory(directory: Path) -> None:
    """
    Create a metadata/cache directory and hide its enclosing .fits folder.

    Explicit directory creation keeps path lookup from creating artifacts.
    Non-.fits destinations (such as a custom log directory) remain visible.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for parent in (directory, *directory.parents):
        if parent.name in {FITS_DIR_NAME, ".fits_experiment"}:
            hide_on_windows(parent)
            break


def logs_dir(root: Path) -> Path:
    """
    Return the directory containing FITS log files.
    """
    return fits_dir(root) / LOGS_DIR_NAME


def reports_dir(root: Path) -> Path:
    """
    Return the directory containing FITS run reports.
    """
    return fits_dir(root) / REPORTS_DIR_NAME


EXPERIMENT_DIR_NAME = '.fits_experiment'
STATE_DIR_NAME = 'experiment_state'
STATE_FILENAME = 'experiment_state.json'
BACKUP_DIR_NAME = 'backup'
INTERNAL_DIR_NAMES = {FITS_DIR_NAME, EXPERIMENT_DIR_NAME}


def acquisition_root(workdir: Path) -> Path:
    """
    Locate the portable acquisition owning a series, independent of state location.
    """
    directory = workdir.expanduser().resolve()
    for candidate in (directory, *directory.parents):
        if (candidate / EXPERIMENT_DIR_NAME).is_dir():
            return candidate
    return directory.parent


def experiment_metadata(workdir: Path, category: str) -> Path:
    """
    Return acquisition-local metadata for one series; never create directories.
    """
    root = acquisition_root(workdir)
    directory = root / EXPERIMENT_DIR_NAME
    hide_on_windows(directory)
    return directory / category / workdir.name


def experiment_state_path(workdir: Path, *, acquisition: Path | None = None) -> Path:
    """
    Experiment state path.
    """
    root = acquisition if acquisition is not None else acquisition_root(workdir)
    return root / EXPERIMENT_DIR_NAME / STATE_DIR_NAME / workdir.name / STATE_FILENAME


def experiment_cache(workdir: Path) -> Path:
    """
    Experiment cache.
    """
    root = acquisition_root(workdir)
    if not (root / EXPERIMENT_DIR_NAME).is_dir():
        key = hashlib.sha256(str(workdir.resolve()).encode()).hexdigest()[:20]
        return Path(tempfile.gettempdir()) / 'fits-viewer-cache' / key
    return experiment_metadata(workdir, 'cache')


def experiment_tuning(workdir: Path) -> Path:
    """
    Experiment tuning.
    """
    return experiment_metadata(workdir, 'tuning')


def experiment_backup(workdir: Path) -> Path:
    """
    Return acquisition-local retained backups for this series.
    """
    return experiment_metadata(workdir, BACKUP_DIR_NAME)


def backups_dir(root: Path) -> Path:
    """
    Return retained whole-run backups separately from acquisition-local backups.
    """
    return fits_dir(root) / BACKUP_DIR_NAME


def is_internal_path(path: Path, root: Path) -> bool:
    """
    Return whether a path belongs to FITS-owned metadata, cache or history.
    """
    return any(part in INTERNAL_DIR_NAMES for part in path.relative_to(root).parts)
