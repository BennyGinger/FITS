from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def serialize_experiment_state(state: Any) -> dict[str, Any]:
    return {
        "run_dir": str(state.run_dir),
        "original_image_rel": str(state.original_image_rel),
        "image_rel": str(state.image_rel) if state.image_rel is not None else None,
        "masks_rel": str(state.masks_rel) if state.masks_rel is not None else None,
        "last_step": state.last_step,
        "experiment_id": state.experiment_id,
        "series_index": state.series_index,
        "step_status": state.step_status,
        "step_settings_hash": state.step_settings_hash,
        "last_error": state.last_error,
        "updated_at": state.updated_at.isoformat() if state.updated_at is not None else None,
    }


def deserialize_experiment_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TypeError("Experiment state JSON root must be an object.")

    def required(name: str) -> Any:
        if name not in raw:
            raise KeyError(f"Missing required key: {name}")
        return raw[name]

    def as_path(name: str, value: Any) -> Path:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string path.")
        return Path(value)

    def as_optional_path(name: str, value: Any) -> Path | None:
        if value is None:
            return None
        return as_path(name, value)

    def as_optional_str(name: str, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string or null.")
        return value

    def as_int(name: str, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer.")
        return value

    def as_str_map(name: str, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            raise TypeError(f"{name} must be an object of string keys/values.")
        out: dict[str, str] = {}
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise TypeError(f"{name} must contain only string keys/values.")
            out[k] = v
        return out

    def as_optional_datetime(name: str, value: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{name} must be an ISO datetime string or null.")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} is not a valid ISO datetime.") from exc

    return {
        "run_dir": as_path("run_dir", required("run_dir")),
        "original_image_rel": as_path("original_image_rel", required("original_image_rel")),
        "image_rel": as_optional_path("image_rel", raw.get("image_rel")),
        "masks_rel": as_optional_path("masks_rel", raw.get("masks_rel")),
        "last_step": as_optional_str("last_step", raw.get("last_step")),
        "experiment_id": as_optional_str("experiment_id", raw.get("experiment_id")),
        "series_index": as_int("series_index", required("series_index")),
        "step_status": as_str_map("step_status", raw.get("step_status", {})),
        "step_settings_hash": as_str_map("step_settings_hash", raw.get("step_settings_hash", {})),
        "last_error": as_optional_str("last_error", raw.get("last_error")),
        "updated_at": as_optional_datetime("updated_at", raw.get("updated_at")),
    }
