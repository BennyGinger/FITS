from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from typing import TypeAlias

from fits.environment.serialization import deserialize_experiment_state, serialize_experiment_state


StepError: TypeAlias = tuple[str, str]  # (step_name, error_message)


@dataclass(frozen=True)
class ExperimentState:
    """
    Minimal durable state for a single experiment branch.
    """

    workdir: Path
    original_image_rel: Path
    image_rel: Path | None = None
    masks_rel: Path | None = None
    completed_steps: tuple[str, ...] = ()
    last_error: StepError | None = None
    updated_at: datetime | None = None

    @classmethod
    def init(cls, workdir: Path, original_image: Path) -> ExperimentState:
        """
        Initialize a new ExperimentState with the given working directory and original image path.

        Args:
            workdir: Working directory for this experiment branch.
            original_image: Path to the original image file. Stored as a path relative to ``workdir``.

        Returns:
            An initialized ExperimentState instance with relative paths set.
        """
        return cls(workdir=workdir, original_image_rel=cls._to_relative(workdir, original_image), updated_at=datetime.now())

    def with_image(self, image_path: Path) -> ExperimentState:
        """Return a new ExperimentState with the image path set."""
        return replace(self, image_rel=self._to_relative(self.workdir, image_path), updated_at=datetime.now())

    def with_masks(self, masks_path: Path) -> ExperimentState:
        """Return a new ExperimentState with the masks path set."""
        return replace(self, masks_rel=self._to_relative(self.workdir, masks_path), updated_at=datetime.now())

    def with_completed_step(self, step_name: str) -> ExperimentState:
        """Append a completed step once, preserving insertion order."""
        if step_name in self.completed_steps:
            return self
        return replace(self,
                       completed_steps=(*self.completed_steps, step_name),
                       last_error=None,
                       updated_at=datetime.now(),)

    def with_error(self, step_name: str, error_message: str) -> ExperimentState:
        """Record the latest step failure as ``(step_name, error_message)``."""
        return replace(self,
                       last_error=(step_name, error_message),
                       updated_at=datetime.now(),)

    def to_json(self) -> ExperimentState:
        """Save the state to ``workdir/experiment_state.json`` and return ``self``."""
        target_path = self.workdir / "experiment_state.json"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(serialize_experiment_state(self), indent=2, sort_keys=True)
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
    def from_json(cls, workdir: Path) -> ExperimentState:
        """Load an experiment state from ``workdir/experiment_state.json``. The passed ``workdir`` is authoritative."""
        json_path = workdir / "experiment_state.json"
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        return cls(workdir=workdir, **deserialize_experiment_state(raw))

    def save(self) -> ExperimentState:
        """Alias for ``to_json`` for clearer call sites."""
        return self.to_json()

    @classmethod
    def load(cls, workdir: Path) -> ExperimentState:
        """Alias for ``from_json`` for clearer call sites."""
        return cls.from_json(workdir)
    
    @property
    def original_image(self) -> Path:
        """Get the absolute path to the original image."""
        return self._to_absolute(self.original_image_rel)

    @property
    def image(self) -> Path | None:
        """Get the absolute path to the FITS image, or None if not set."""
        return self._to_absolute(self.image_rel) if self.image_rel is not None else None

    @property
    def masks(self) -> Path | None:
        """Get the absolute path to the FITS masks, or None if not set."""
        return self._to_absolute(self.masks_rel) if self.masks_rel is not None else None

    @property
    def experiment_id(self) -> str:
        """Stable branch id derived from the materialized workdir."""
        return self.workdir.as_posix()

    @property
    def series_index(self) -> int | None:
        """Series index derived from a ``*_sX`` workdir suffix when available."""
        parts = self.workdir.name.rsplit("_s", 1)
        if len(parts) != 2 or not parts[1]:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

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


