"""Top-level metadata stored with FITS workflow artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from fits.environment.constant import ChannelScope, DIST_FITS, StepName
from fits.workflows.metadata.run import RunMetadata
from fits.workflows.metadata.step import StepMetadata


@dataclass(slots=True, frozen=True)
class FitsMeta:
    """
    Combine run provenance and metadata for completed workflow steps.
    """

    _run: RunMetadata = field(default_factory=RunMetadata)
    _steps: dict[StepName, StepMetadata] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_steps", dict(self._steps))

    @classmethod
    def init(cls, *, user_name: str | None = None, created_by: str = DIST_FITS,) -> FitsMeta:
        """
        Create metadata for a new pipeline run.
        """
        return cls(_run=RunMetadata(
            created_by=created_by, user_name=user_name))

    @property
    def run(self) -> RunMetadata:
        """
        Return run-level provenance metadata.
        """
        return self._run

    @property
    def steps(self) -> dict[StepName, StepMetadata]:
        """
        Return metadata indexed by workflow step.
        """
        return self._steps

    def with_step(self,
                step_name: StepName,
                created_by: str,
                exported_channel: ChannelScope = None,
                params: Mapping[str, Any] | None = None,
                ) -> FitsMeta:
        """
        Return a copy with metadata recorded for one workflow step.
        """
        steps_map = dict(self._steps)
        current_step = steps_map.get(step_name)
        if current_step is None:
            updated_step = StepMetadata.create(step_name=step_name,
                                            created_by=created_by,
                                            exported_channel=exported_channel,
                                            params=params,)
        else:
            if current_step.created_by != created_by:
                raise ValueError(f"Step '{step_name}' was previously created by "
                                f"'{current_step.created_by}', cannot add metadata from "
                                f"'{created_by}'.")
            updated_step = current_step.with_params(exported_channel=exported_channel,
                                                    params=params)
        steps_map[step_name] = updated_step
        return replace(self, _steps=steps_map)

    def completed_channels(self, step_name: StepName) -> list[int]:
        """
        Return processed source-channel indices for a workflow step.
        """
        step_meta = self._steps.get(step_name)
        if step_meta is None:
            return []
        return [channel_meta.channel for channel_meta in step_meta.channels.values()]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FitsMeta:
        """
        Create FITS metadata from its serialized representation.
        """
        run_data = data.get("pipeline_meta", {})
        if not isinstance(run_data, Mapping):
            raise TypeError("'pipeline_meta' must be a mapping.")
        
        steps_data = data.get("steps", {})
        if not isinstance(steps_data, Mapping):
            raise TypeError("'steps' must be a mapping.")
        
        steps_metadata: dict[StepName, StepMetadata] = {}
        for key, value in steps_data.items():
            if not isinstance(value, Mapping):
                raise TypeError(f"Metadata for step {str(key)!r} must be a mapping.")
            
            step_name = StepName(key)
            step_meta = StepMetadata.from_dict(value)
            
            if step_meta.step_name != step_name:
                raise ValueError(
                    f"Step key {str(key)!r} does not match the embedded step "
                    f"name {step_meta.step_name.value!r}.")
            steps_metadata[step_name] = step_meta
        return cls(_run=RunMetadata.from_dict(run_data),
                   _steps=steps_metadata,)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize metadata for storage with a FITS artifact.
        """
        return {"pipeline_meta": self._run.to_dict(),
                "steps": {key: value.to_dict() for key, value in self._steps.items()},}
