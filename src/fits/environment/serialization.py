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
        "completed_steps": list(state.completed_steps),
        "last_error": list(state.last_error) if state.last_error is not None else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at is not None else None,
    }


def deserialize_experiment_state(raw: Any) -> dict[str, Any]:
    """Validate/decode persisted JSON and return kwargs for ``ExperimentState(**kwargs)``."""
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

    def as_optional_datetime(name: str, value: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{name} must be an ISO datetime string or null.")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} is not a valid ISO datetime.") from exc

    def as_completed_steps(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise TypeError("completed_steps must be an array of step names.")

        ordered_unique: list[str] = []
        seen: set[str] = set()
        for idx, item in enumerate(value):
            if not isinstance(item, str):
                raise TypeError(f"completed_steps[{idx}] must be a string.")
            if item in seen:
                continue
            seen.add(item)
            ordered_unique.append(item)
        return tuple(ordered_unique)

    def as_last_error(value: Any, last_step_hint: str | None) -> tuple[str, str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            # Legacy shape: a plain error message string.
            step_name = last_step_hint or "unknown"
            return (step_name, value)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            step_name, message = value
            if not isinstance(step_name, str) or not isinstance(message, str):
                raise TypeError("last_error tuple members must be strings.")
            return (step_name, message)
        raise TypeError("last_error must be null, a string, or [step_name, error_message].")

    def as_step_status_map(value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError("step_status must be an object of string keys/values.")
        out: dict[str, str] = {}
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise TypeError("step_status must contain only string keys/values.")
            out[k] = v
        return out

    def as_legacy_step_meta(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError("step_meta must be an object.")
        for k in value.keys():
            if not isinstance(k, str):
                raise TypeError("step_meta must have string keys.")
        return value

    def is_legacy_step_done(meta: Any) -> bool:
        if not isinstance(meta, dict):
            return False
        if meta.get("status") == "done":
            return True

        channels = meta.get("channels")
        if not isinstance(channels, dict) or not channels:
            return False

        for value in channels.values():
            if not isinstance(value, dict) or value.get("status") != "done":
                return False
        return True

    completed_steps: tuple[str, ...]
    if "completed_steps" in raw:
        completed_steps = as_completed_steps(raw.get("completed_steps"))
    else:
        # Legacy migration path.
        done_ordered: list[str] = []
        seen: set[str] = set()

        for step_name, meta in as_legacy_step_meta(raw.get("step_meta")).items():
            if is_legacy_step_done(meta) and step_name not in seen:
                seen.add(step_name)
                done_ordered.append(step_name)

        for step_name, status in as_step_status_map(raw.get("step_status")).items():
            if status == "done" and step_name not in seen:
                seen.add(step_name)
                done_ordered.append(step_name)

        completed_steps = tuple(done_ordered)

    last_step_hint = as_optional_str("last_step", raw.get("last_step"))
    last_error = as_last_error(raw.get("last_error"), last_step_hint)

    updated_at = as_optional_datetime("updated_at", raw.get("updated_at"))

    return {
        "run_dir": as_path("run_dir", required("run_dir")),
        "original_image_rel": as_path("original_image_rel", required("original_image_rel")),
        "image_rel": as_optional_path("image_rel", raw.get("image_rel")),
        "masks_rel": as_optional_path("masks_rel", raw.get("masks_rel")),
        "completed_steps": completed_steps,
        "last_error": last_error,
        # Keep snapshots timestamped even when loading legacy payloads without updated_at.
        "updated_at": updated_at or datetime.now(),
    }