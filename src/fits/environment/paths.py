"""Paths for FITS-owned run metadata."""

from pathlib import Path

from fits.environment.hidden import hide_on_windows


FITS_DIR_NAME = ".fits"
LOGS_DIR_NAME = "logs"
REPORTS_DIR_NAME = "reports"


def fits_dir(root: Path) -> Path:
    """Return the FITS metadata directory below a run or override root."""
    directory = root.expanduser().resolve() / FITS_DIR_NAME
    hide_on_windows(directory)
    return directory


def ensure_fits_directory(directory: Path) -> None:
    """Create a metadata/cache directory and hide its enclosing .fits folder.

    Explicit directory creation keeps path lookup from creating artifacts.
    Non-.fits destinations (such as a custom log directory) remain visible.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for parent in (directory, *directory.parents):
        if parent.name == FITS_DIR_NAME:
            hide_on_windows(parent)
            break


def logs_dir(root: Path) -> Path:
    """Return the directory containing FITS log files."""
    return fits_dir(root) / LOGS_DIR_NAME


def reports_dir(root: Path) -> Path:
    """Return the directory containing FITS run reports."""
    return fits_dir(root) / REPORTS_DIR_NAME
