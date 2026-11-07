"""Serialization and validation for persisted experiment states."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, TYPE_CHECKING
from fits.workflows.metadata import FitsMeta


if TYPE_CHECKING:
    from fits.workflows.experiments.model import ExperimentState


def serialize_experiment_state(state: ExperimentState) -> dict[str, Any]:
    """
    Convert an experiment state into its JSON-compatible payload.
    """
    return {"excluded": state.excluded,
            "compacted": state.compacted,
            "migration_checkpoint": state.migration_checkpoint,
            "compaction_conflicts_accepted": state.compaction_conflicts_accepted,
            "artifacts": {kind: path.as_posix() for kind, path in state.artifacts.items()},
            "completed_steps": list(state.completed_steps),
            "updated_at": (
                state.updated_at.isoformat() if state.updated_at is not None else None),
            "meta": state.metadata.to_dict(),}


def deserialize_experiment_state(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Validate persisted JSON and return arguments for ``ExperimentState``.
    """
    if not isinstance(raw, dict):
        raise TypeError("Experiment state JSON root must be an object.")

    def required(name: str) -> Any:
        """
        Read a required field from the serialized experiment state.
        """
        if name not in raw:
            raise KeyError(f"Missing required key: {name}")
        return raw[name]

    def as_path(name: str, value: Any) -> Path:
        """
        Parse and validate the path field.
        """
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string path.")
        return Path(PureWindowsPath(value).as_posix() if "\\" in value else value)

    def as_artifacts(value: Any) -> dict[str, Path]:
        """
        Parse and validate the artifacts field.
        """
        if not isinstance(value, dict):
            raise TypeError("artifacts must be an object of string keys and string paths.")

        artifacts: dict[str, Path] = {}
        for kind, path_value in value.items():
            if not isinstance(kind, str):
                raise TypeError("artifacts must use string keys.")
            kind = {"image_archived": "image_compacted", "mask_archived": "mask_compacted"}.get(kind, kind)
            artifacts[kind] = as_path(f"artifacts[{kind!r}]", path_value)
        if "raw_image" not in artifacts:
            raise KeyError("Missing required artifact: raw_image")
        return artifacts

    def as_optional_datetime(name: str, value: Any) -> datetime | None:
        """
        Parse and validate the optional datetime field.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{name} must be an ISO datetime string or null.")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} is not a valid ISO datetime.") from exc

    def as_meta(value: Any) -> FitsMeta:
        """
        Parse and validate the meta field.
        """
        if value is None:
            return FitsMeta()
        if not isinstance(value, dict):
            raise TypeError("meta must be an object.")
        return FitsMeta.from_dict(value)

    def as_completed_steps(value: Any) -> tuple[str, ...]:
        """
        Parse and validate the completed steps field.
        """
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise TypeError("completed_steps must be an array of step names.")
        ordered_unique: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, str):
                raise TypeError(f"completed_steps[{index}] must be a string.")
            if item not in seen:
                seen.add(item)
                ordered_unique.append(item)
        return tuple(ordered_unique)

    return {"excluded": raw.get("excluded") is True,
            "compacted": bool(raw.get("compacted", raw.get("archived", False))),
            "migration_checkpoint": raw.get("migration_checkpoint"),
            "compaction_conflicts_accepted": bool(raw.get("compaction_conflicts_accepted", raw.get("archive_conflicts_accepted", False))),
            "artifacts": as_artifacts(required("artifacts")),
            "completed_steps": as_completed_steps(raw.get("completed_steps")),
            "metadata": as_meta(raw.get("meta")),
            "updated_at": (as_optional_datetime("updated_at", raw.get("updated_at"))
                            or datetime.now()),}
