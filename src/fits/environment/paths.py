"""Paths for FITS-owned run metadata."""

from pathlib import Path


FITS_DIR_NAME = ".fits"
LOGS_DIR_NAME = "logs"
REPORTS_DIR_NAME = "reports"


def fits_dir(root: Path) -> Path:
    """Return the FITS metadata directory below a run or override root."""
    return root.expanduser().resolve() / FITS_DIR_NAME


def logs_dir(root: Path) -> Path:
    """Return the directory containing FITS log files."""
    return fits_dir(root) / LOGS_DIR_NAME


def reports_dir(root: Path) -> Path:
    """Return the directory containing FITS run reports."""
    return fits_dir(root) / REPORTS_DIR_NAME
