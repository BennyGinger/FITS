from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any


@dataclass(frozen=True)
class StepProfile:
    distribution: str
    step_name: str


def _get_dist_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def build_provenance_stamp(distribution: str) -> dict[str, Any]:
    """Create a standard provenance stamp for a workflow step."""
    return {
        "distribution": distribution,
        "version": _get_dist_version(distribution),
        "timestamp": _utc_now(),
    }

