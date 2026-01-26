from importlib.metadata import version, PackageNotFoundError
from datetime import datetime, timezone
from typing import Any, Mapping


PIPELINE_TAG = 65000

def get_dist_version(dist_name: str) -> str:
    try:
        return version(dist_name)
    except PackageNotFoundError:
        return "unknown"

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def add_step(custom_metadata: Mapping[str, Any] | None, *, dist_name: str, step: str) -> dict[str, Any]:
    """
    Small helper to add a processing step to the custom metadata.
    Args:
        custom_metadata: Existing custom metadata mapping, or None.
        dist_name: Name of the distribution adding the step.
        step: Name of the processing step.
    Returns:
        Updated custom metadata dictionary including the new step.
        """
    
    out = dict(custom_metadata or {})
    
    out[step] = {
        "dist": dist_name,
        "version": get_dist_version(dist_name),
        "timestamp": utc_now_iso(),
    }
    return out


def is_processed(custom_metadata: Mapping[str, Any] | None, *, step: str) -> bool:
    if not isinstance(custom_metadata, Mapping):
        return False
    return step in custom_metadata

def get_timestamp(custom_metadata: Mapping[str, Any] | None, *, step: str) -> str | None:
    if not is_processed(custom_metadata, step=step):
        return None
    step_metadata = custom_metadata.get(step) if custom_metadata is not None else None
    if not isinstance(step_metadata, Mapping):
        return None
    timestamp = step_metadata.get("timestamp")
    if not isinstance(timestamp, str):
        return None
    return timestamp