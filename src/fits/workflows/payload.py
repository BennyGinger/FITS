import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from fits.workflows.provenance import StepProfile
from fits.settings.models import SettingsModel


EXCULDE_META_KEYS = {"step_name"}

def build_fits_payload(step_profile: StepProfile, **kwargs) -> dict[str, Any]:
    
    provenance_info: dict[str, Any] = step_profile.dump()
    provenance_info.update(**kwargs)
    return provenance_info

def _json_serializer(obj):
    """Custom JSON serializer for non-standard types."""
    if isinstance(obj, Path):
        return str(obj)
    elif isinstance(obj, datetime.datetime):
        return obj.isoformat()
    else:
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def _stable_hash(obj: Any, length: int = 16) -> str:
    payload_json = json.dumps(obj, sort_keys=True, default=_json_serializer)
    return hashlib.sha256(payload_json.encode()).hexdigest()[:length]

def _filter_payload(payload: dict[str, Any], *, exclude_keys: set[str]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in exclude_keys}

def hash_payload(payload: dict[str, Any], *, meta_keys: set[str] = EXCULDE_META_KEYS, length: int = 16) -> str:
    filtered_payload = _filter_payload(payload, exclude_keys=meta_keys)
    return _stable_hash(filtered_payload, length)
