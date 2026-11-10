"""Shared values used when creating provenance metadata."""

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version


def same_producer(first: str, second: str) -> bool:
    """
    Treat the historical I/O distribution name as the same producer after renaming.
    """
    aliases = {'fits-io': 'scope-io', 'fits': 'fisch'}
    first = first.lower().replace('_', '-')
    second = second.lower().replace('_', '-')
    return aliases.get(first, first) == aliases.get(second, second)


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
