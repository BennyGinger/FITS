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
    
    run_dir: Path
    original_image_rel: Path
    image_rel: Path | None = None
    masks_rel: Path | None = None
    completed_steps: tuple[str, ...] = ()
    last_error: StepError | None = None
    updated_at: datetime | None = None

    @classmethod
    def init(cls, run_dir: Path, original_image: Path) -> ExperimentState:
        """
        Initialize a new ExperimentState with the given run directory and original image path.
        
        Args:
            run_dir: Base directory for the current run.
            original_image: Path to the original image file. This will be stored as a relative path to run_dir in the state.
            
        Returns:
            An initialized ExperimentState instance with relative paths set.
        """
        return cls(
            run_dir=run_dir,
            original_image_rel=cls._to_relative(run_dir, original_image),
            updated_at=datetime.now()
        )

    def with_image(self, image_path: Path) -> ExperimentState:
        """
        Return a new ExperimentState with the image path set.
        """
        return replace(
            self,
            image_rel=self._to_relative(self.run_dir, image_path),
            updated_at=datetime.now(),
        )

    def with_masks(self, masks_path: Path) -> ExperimentState:
        """
        Return a new ExperimentState with the masks path set.
        """
        return replace(
            self,
            masks_rel=self._to_relative(self.run_dir, masks_path),
            updated_at=datetime.now(),
        )

    def with_completed_step(self, step_name: str) -> ExperimentState:
        """Append a completed step once, preserving insertion order."""
        if step_name in self.completed_steps:
            return self
        return replace(
            self,
            completed_steps=(*self.completed_steps, step_name),
            last_error=None,
            updated_at=datetime.now(),
        )

    def with_error(self, step_name: str, error_message: str) -> ExperimentState:
        """Record the latest step failure as ``(step_name, error_message)``."""
        return replace(
            self,
            last_error=(step_name, error_message),
            updated_at=datetime.now(),
        )

    def to_json(self) -> ExperimentState:
        """
        Save the state to ``workdir/experiment_state.json`` and return ``self``.
        """
        if self.workdir is None:
            raise ValueError("workdir is not available; set image before calling to_json().")
        target_path = self.workdir / "experiment_state.json"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(serialize_experiment_state(self), indent=2, sort_keys=True)
        fd, temp_path_str = tempfile.mkstemp(
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            text=True,
        )
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
        """
        Load an experiment state from ``workdir/experiment_state.json``.
        """
        json_path = workdir / "experiment_state.json"
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        # ``deserialize_experiment_state`` returns validated kwargs for ``ExperimentState``.
        return cls(**deserialize_experiment_state(raw))

    def save(self) -> ExperimentState:
        """Alias for ``to_json`` for clearer call sites."""
        return self.to_json()

    @classmethod
    def load(cls, workdir: Path) -> ExperimentState:
        """Alias for ``from_json`` for clearer call sites."""
        return cls.from_json(workdir)
    
    @property
    def workdir(self) -> Path | None:
        """
        Get the working directory for the experiment, which is the parent directory of the FITS array.
        """
        return self.image.parent if self.image is not None else None

    @property
    def original_image(self) -> Path:
        """
        Get the absolute path to the original image by resolving the relative path against run_dir.
        """
        return self._to_absolute(self.original_image_rel)

    @property
    def image(self) -> Path | None:
        """
        Get the absolute path to the FITS image, or None if not set.
        """
        return self._to_absolute(self.image_rel) if self.image_rel is not None else None

    @property
    def masks(self) -> Path | None:
        """
        Get the absolute path to the FITS masks, or None if not set.
        """
        return self._to_absolute(self.masks_rel) if self.masks_rel is not None else None

    @property
    def experiment_id(self) -> str | None:
        """Stable branch id derived from the materialized workdir."""
        wd = self.workdir
        return wd.as_posix() if wd is not None else None

    @property
    def series_index(self) -> int | None:
        """Series index derived from a ``*_sX`` workdir suffix when available."""
        wd = self.workdir
        if wd is None:
            return None
        parts = wd.name.rsplit("_s", 1)
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

    @staticmethod
    def _to_relative(base_dir: Path, path: Path) -> Path:
        """
        Convert an absolute path to be relative to ``base_dir``.
        
        If ``path`` is already relative, return it as-is.
        If ``path`` is absolute but not under ``base_dir``, raise ``ValueError``.
        
        Args:
            base_dir: Base directory to which the path should be made relative.
            path: Path to convert.
            
        Returns:
            Path relative to ``base_dir``.
        """
        if path.is_absolute():
            try:
                return path.relative_to(base_dir)
            except ValueError:
                raise ValueError(f"{path} is not under run_dir {base_dir}")
        return path

    def _to_absolute(self, path: Path) -> Path:
        """
        Convert a path to be absolute relative to run_dir.
        
        If path is already absolute, returns it as-is.
        
        Args:
            path: Path to convert (relative to run_dir or already absolute).
            
        Returns:
            Absolute path resolved from run_dir, or original if already absolute.
        """
        if not path.is_absolute():
            return self.run_dir / path
        return path


