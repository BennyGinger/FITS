"""Immutable workflow state for one experiment branch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
import os
from pathlib import Path
from typing import Any

from fits.environment.constant import ARTI_RAW, ArtifactType, ChannelScope, StepName
from fits.workflows.metadata import FitsMeta


@dataclass(slots=True, frozen=True)
class ExperimentState:
    """
    Represent the durable workflow state of one experiment branch.
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
        Create an initial state for a raw image.
        """
        artifacts: dict[ArtifactType, Path] = {ARTI_RAW: cls._to_relative(workdir, original_image)}
        return cls(workdir=workdir,
                    artifacts=artifacts,
                    updated_at=datetime.now(),
                    metadata=fits_meta if fits_meta is not None else FitsMeta(),)

    def with_metadata(self,
                        *,
                        step_name: StepName,
                        created_by: str,
                        exported_channel: ChannelScope = None,
                        channels_params: Mapping[str, Any] | None = None,
                        ) -> ExperimentState:
        """
        Return a copy with metadata recorded for a workflow step.
        """
        return replace(self,
                        metadata=self.metadata.with_step(step_name=step_name,
                                                        created_by=created_by,
                                                        exported_channel=exported_channel,
                                                        params=channels_params,),)

    def with_complete_step(self,
                            *,
                            step_name: StepName,
                            artifact_kind: ArtifactType,
                            artifact_path: Path,
                            workdir: Path | None = None,
                            ) -> ExperimentState:
        """
        Return a copy containing a completed step and its output artifact.
        """
        target_workdir = self.workdir if workdir is None else workdir
        artifacts = {kind: self._to_relative(target_workdir, self._to_absolute(path))
                        for kind, path in self.artifacts.items()}
        artifacts[artifact_kind] = self._to_relative(target_workdir, artifact_path)
        completed_steps = self.completed_steps
        if step_name not in completed_steps:
            completed_steps = (*completed_steps, step_name)
        return replace(self,
                        workdir=target_workdir,
                        artifacts=artifacts,
                        completed_steps=completed_steps,
                        updated_at=datetime.now(),)

    def artifact(self, kind: ArtifactType) -> Path | None:
        """
        Return the absolute artifact path for a kind when present.
        """
        relative = self.artifacts.get(kind)
        return self._to_absolute(relative) if relative is not None else None

    def completed_channels(self, step_name: StepName) -> list[int]:
        """
        Return source-channel indices completed for a workflow step.
        """
        return self.metadata.completed_channels(step_name)

    @property
    def original_image(self) -> Path:
        """
        Return the absolute path to the original image.
        """
        return self._to_absolute(self.artifacts[ARTI_RAW])

    @property
    def experiment_id(self) -> str:
        """
        Return the stable branch identifier derived from its work directory.
        """
        return self.workdir.as_posix()

    @property
    def metadata_dump(self) -> dict[str, Any]:
        """
        Return serialized FITS metadata for this state.
        """
        return self.metadata.to_dict()

    @property
    def last_step(self) -> str | None:
        """
        Return the most recently completed step, if any.
        """
        return self.completed_steps[-1] if self.completed_steps else None

    def workdir_relative(self, run_dir: Path | None) -> Path:
        """
        Return the work directory relative to the run directory when possible.
        """
        if run_dir is None:
            return self.workdir
        try:
            return self.workdir.relative_to(run_dir)
        except ValueError:
            return self.workdir

    @staticmethod
    def _to_relative(base_dir: Path, path: Path) -> Path:
        """
        Store an absolute path relative to an experiment work directory.
        """
        return Path(os.path.relpath(path, base_dir)) if path.is_absolute() else path

    def _to_absolute(self, path: Path) -> Path:
        """
        Resolve a stored path against the experiment work directory.
        """
        return (self.workdir / path).resolve() if not path.is_absolute() else path
