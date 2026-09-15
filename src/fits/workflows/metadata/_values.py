"""Shared values used when creating provenance metadata."""

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version


def distribution_version(distribution: str) -> str:
    """
    Return an installed distribution version or ``unknown``.
    """
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def utc_now() -> str:
    """
    Return the current UTC time in the metadata timestamp format.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
