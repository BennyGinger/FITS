from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from fits.environment.constant import ArtifactType, StepName
from fits.workflows.metadata.models import FitsMeta



@dataclass(slots=True, frozen=True)
class ExperimentState:
    """
    Minimal durable state for a single experiment branch.
    """

    workdir: Path
    artifacts: dict[ArtifactType, Path] = field(default_factory=dict)
    completed_steps: tuple[str, ...] = ()
    updated_at: datetime | None = None
    metadata: FitsMeta = field(default_factory=FitsMeta)

    @classmethod
    def init(cls, 
             workdir: Path, 
             original_image: Path, 
             *, 
             fits_meta: FitsMeta | None = None,
             ) -> ExperimentState:
        """
        Initialize a new ExperimentState with the given working directory and original image path.

        Args:
            workdir: Working directory for this experiment branch.
            original_image: Path to the original image file. Stored as a path relative to ``workdir``.
            fits_meta: Optional initial metadata. A new empty ``FitsMeta`` is created when omitted.

        Returns:
            An initialized ExperimentState instance with relative paths set.
        """
        artifacts: dict[ArtifactType, Path] = {"raw_image": cls._to_relative(workdir, original_image)}
        return cls(workdir=workdir, 
                   artifacts=artifacts, 
                   updated_at=datetime.now(),
                   metadata=fits_meta if fits_meta is not None else FitsMeta())

    def with_metadata(self,
                        *,
                        step_name: StepName,
                        created_by: str,
                        exported_channel_indices: Sequence[int] | None = None,
                        channels_params: Mapping[str, Any] | None = None,
                        ) -> ExperimentState:
        """
        Return a new ExperimentState with updated FITS metadata for the given step.
        """
        return replace(self,
                       metadata=self.metadata.with_step(step_name=step_name,
                                                        created_by=created_by,
                                                        exported_channel_indices=exported_channel_indices,
                                                        channels_params=channels_params,),)
    
    def with_complete_step(self, 
                         *, 
                         step_name: StepName, 
                         artifact_kind: ArtifactType, 
                         artifact_path: Path,
                         workdir: Path | None = None,
                         ) -> ExperimentState:
        """
        Return a new state produced by successful completion of a workflow step.

        The returned state contains the new artifact, completed-step entry,
        and updated FITS metadata. The current state remains unchanged.
        """
        target_workdir = self.workdir if workdir is None else workdir
        
        # Copy the existing artifacts and update it with the new artifact path
        artifacts = {kind: self._to_relative(target_workdir, self._to_absolute(path),)
                     for kind, path in self.artifacts.items()}
        artifacts[artifact_kind] = self._to_relative(target_workdir, artifact_path,)
        
        # Update the completed steps
        completed_steps = self.completed_steps
        if step_name not in completed_steps:
            completed_steps = (*completed_steps, step_name)
        
        return replace(self, 
                       workdir=target_workdir,
                       artifacts=artifacts, 
                       completed_steps=completed_steps,
                       updated_at=datetime.now())

    def artifact(self, kind: ArtifactType) -> Path | None:
        """
        Get the absolute path to the artifact of the given kind, or None if not set.
        """
        rel = self.artifacts.get(kind)
        return self._to_absolute(rel) if rel is not None else None

    def completed_channels(self, step_name: StepName) -> list[int]:
        """
        Get the list of channel indices that have been completed for the given step.
        """
        return self.metadata.completed_channels(step_name)
    
    def save_state(self) -> ExperimentState:
        """
        Save the state to ``workdir/experiment_state.json`` and return ``self``.
        """
        target_path = self.workdir / "experiment_state.json"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(_serialize_experiment_state(self), indent=2)
        fd, temp_path_str = tempfile.mkstemp(dir=target_path.parent,
                                             prefix=f".{target_path.name}.",
                                             suffix=".tmp",
                                             text=True)
        temp_path = Path(temp_path_str)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target_path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        return self

    @classmethod
    def load_state(cls, workdir: Path) -> ExperimentState:
        """
        Load an experiment state from ``workdir/experiment_state.json``. The passed ``workdir`` is authoritative."""
        json_path = workdir / "experiment_state.json"
        raw: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
        return cls(workdir=workdir, **_deserialize_experiment_state(raw))

    @property
    def original_image(self) -> Path:
        """Get the absolute path to the original image."""
        return self._to_absolute(self.artifacts["raw_image"])

    @property
    def image(self) -> Path | None:
        """Get the absolute path to the FITS image, or None if not set."""
        return self.artifact("image")

    @property
    def seg_masks(self) -> Path | None:
        """Get the absolute path to the FITS masks, or None if not set."""
        return self.artifact("segmentation")

    @property
    def track_masks(self) -> Path | None:
        """Get the absolute path to the FITS tracking masks, or None if not set."""
        return self.artifact("tracking")
    
    @property
    def experiment_id(self) -> str:
        """Stable branch id derived from the materialized workdir."""
        return self.workdir.as_posix()

    @property
    def metadata_dump(self) -> dict[str, Any]:
        """Return a dictionary representation of the FITS metadata for this experiment state."""
        return self.metadata.to_dict()

    @property
    def last_step(self) -> str | None:
        """Most recent successfully completed step, if any."""
        if not self.completed_steps:
            return None
        return self.completed_steps[-1]

    def workdir_relative(self, run_dir: Path | None) -> Path:
        """
        Return workdir relative to run_dir for display purposes.
        If workdir is not under run_dir or run_dir is None, return the absolute workdir.
        """
        if run_dir is None:
            return self.workdir

        try:
            return self.workdir.relative_to(run_dir)
        except ValueError:
            return self.workdir
    
    @staticmethod
    def _to_relative(base_dir: Path, path: Path) -> Path:
        """Convert an absolute path to be relative to ``base_dir``. Accepts paths outside ``base_dir`` (uses ``../``)."""
        if path.is_absolute():
            return Path(os.path.relpath(path, base_dir))
        return path

    def _to_absolute(self, path: Path) -> Path:
        """Resolve a path relative to ``workdir`` to an absolute path."""
        if not path.is_absolute():
            return (self.workdir / path).resolve()
        return path



########## Serialization helpers ##########
def _serialize_experiment_state(state: ExperimentState) -> dict[str, Any]:
    return {
        "artifacts": {kind: str(path) for kind, path in state.artifacts.items()},
        "completed_steps": list(state.completed_steps),
        "updated_at": state.updated_at.isoformat() if state.updated_at is not None else None,
        "meta": state.metadata.to_dict(),
    }


def _deserialize_experiment_state(raw: dict[str, Any]) -> dict[str, Any]:
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

    def as_artifacts(value: Any) -> dict[str, Path]:
        if not isinstance(value, dict):
            raise TypeError("artifacts must be an object of string keys and string paths.")

        artifacts: dict[str, Path] = {}
        for kind, path_value in value.items():
            if not isinstance(kind, str):
                raise TypeError("artifacts must use string keys.")
            artifacts[kind] = as_path(f"artifacts[{kind!r}]", path_value)
        if "raw_image" not in artifacts:
            raise KeyError("Missing required artifact: raw_image")
        return artifacts

    def as_optional_datetime(name: str, value: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{name} must be an ISO datetime string or null.")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} is not a valid ISO datetime.") from exc

    def as_meta(value: Any) -> FitsMeta:
        if value is None:
            return FitsMeta()
        if not isinstance(value, dict):
            raise TypeError("meta must be an object.")
        return FitsMeta.from_dict(value)

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
    completed_steps = as_completed_steps(raw.get("completed_steps"))

    updated_at = as_optional_datetime("updated_at", raw.get("updated_at"))

    artifacts = as_artifacts(required("artifacts"))
    meta = as_meta(raw.get("meta"))

    return {
        "artifacts": artifacts,
        "completed_steps": completed_steps,
        "metadata": meta,
        "updated_at": updated_at or datetime.now(),
    }