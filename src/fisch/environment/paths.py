"""Paths for FIScH-owned run metadata."""

from __future__ import annotations

from pathlib import Path
from fisch.environment.hidden import hide_on_windows
from fisch.environment import naming
import hashlib
import tempfile


RUN_METADATA_DIR_NAME = naming.RUN_METADATA
LOGS_DIR_NAME = "logs"
REPORTS_DIR_NAME = "reports"


def pipeline_dir(root: Path) -> Path:
    """
    Return the FIScH metadata directory below a run or override root.
    """
    directory = root.expanduser().resolve() / RUN_METADATA_DIR_NAME
    hide_on_windows(directory)
    return directory


def ensure_metadata_directory(directory: Path) -> None:
    """
    Create a metadata/cache directory and hide its enclosing .pipeline folder.

    Explicit directory creation keeps path lookup from creating artifacts.
    Non-.pipeline destinations (such as a custom log directory) remain visible.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for parent in (directory, *directory.parents):
        if parent.name in {RUN_METADATA_DIR_NAME, ".acquisition"}:
            hide_on_windows(parent)
            break


def logs_dir(root: Path) -> Path:
    """
    Return the directory containing FIScH log files.
    """
    return pipeline_dir(root) / LOGS_DIR_NAME


def reports_dir(root: Path) -> Path:
    """
    Return the directory containing FIScH run reports.
    """
    return pipeline_dir(root) / REPORTS_DIR_NAME


ACQUISITION_METADATA_DIR_NAME = naming.ACQUISITION_METADATA
STATE_DIR_NAME = 'experiment_state'
STATE_FILENAME = 'experiment_state.json'
BACKUP_DIR_NAME = 'backup'
INTERNAL_DIR_NAMES = naming.INTERNAL_DIRECTORIES


def acquisition_root(workdir: Path) -> Path:
    """
    Locate the portable acquisition owning a series, independent of state location.
    """
    directory = workdir.expanduser().resolve()
    for candidate in (directory, *directory.parents):
        if naming.metadata_directory(candidate, acquisition=True).is_dir():
            return candidate
    return directory.parent


def experiment_metadata(workdir: Path, category: str) -> Path:
    """
    Return acquisition-local metadata for one series; never create directories.
    """
    root = acquisition_root(workdir)
    directory = naming.metadata_directory(root, acquisition=True)
    if directory.name != ACQUISITION_METADATA_DIR_NAME and category in ('cache', 'tuning'):
        key = hashlib.sha256(str(workdir.resolve()).encode()).hexdigest()[:20]
        return Path(tempfile.gettempdir()) / 'pipeline-viewer-cache' / key / category
    hide_on_windows(directory)
    return directory / category / workdir.name


def experiment_state_path(workdir: Path, *, acquisition: Path | None = None, for_write: bool = False) -> Path:
    """
    Experiment state path.
    """
    root = acquisition if acquisition is not None else acquisition_root(workdir)
    directory = root / ACQUISITION_METADATA_DIR_NAME if for_write else naming.metadata_directory(root, acquisition=True)
    return directory / STATE_DIR_NAME / workdir.name / STATE_FILENAME


def experiment_cache(workdir: Path) -> Path:
    """
    Experiment cache.
    """
    root = acquisition_root(workdir)
    if not (root / ACQUISITION_METADATA_DIR_NAME).is_dir():
        key = hashlib.sha256(str(workdir.resolve()).encode()).hexdigest()[:20]
        return Path(tempfile.gettempdir()) / 'pipeline-viewer-cache' / key
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
    return pipeline_dir(root) / BACKUP_DIR_NAME


def is_internal_path(path: Path, root: Path) -> bool:
    """
    Return whether a path belongs to FIScH-owned metadata, cache or history.
    """
    return any(part in INTERNAL_DIR_NAMES for part in path.relative_to(root).parts)
