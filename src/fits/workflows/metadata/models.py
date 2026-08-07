from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from fits.environment.constant import DIST_FITS, StepName, ChannelScope

def _get_dist_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(slots=True, frozen=True)
class RunMetadata:
    """
    Metadata container for a single run of a workflow.
    """
    created_by: str = DIST_FITS
    user_name: str | None = None
    version: str | None = None
    timestamp: str | None = None
    
    def __post_init__(self) -> None:
        if self.version is None:
            object.__setattr__(self, "version", _get_dist_version(self.created_by))
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", _utc_now())
     
    def with_user(self, user_name: str) -> RunMetadata:
        """
        Return a new RunMetadata with the user name set.
        """
        return replace(self, user_name=user_name,
                       version=_get_dist_version(self.created_by),
                       timestamp=_utc_now())
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunMetadata:
        """
        Create a RunMetadata instance from a dictionary representation.
        """
        return cls(created_by=data.get("created_by", DIST_FITS),
                   user_name=data.get("user_name"),
                   version=data.get("version"),
                   timestamp=data.get("timestamp"))
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert the RunMetadata to a dictionary representation.
        """
        return {
            "user_name": self.user_name,
            "created_by": self.created_by,
            "version": self.version,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True, frozen=True)
class ChannelStepMeta:
    channel: int
    params: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str | None = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", _utc_now())
        object.__setattr__(self, "params", dict(self.params))  # Ensure params is a dict
    
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChannelStepMeta:
        """
        Create a ChannelStepMeta instance from a dictionary representation.
        """
        channel = data.get("channel")

        if not isinstance(channel, int) or channel < 0:
            raise ValueError("Channel step metadata must contain a non-negative integer 'channel' field.")
        
        params = {key: value
                  for key, value in data.items()
                  if key not in ("channel", "timestamp")}
        return cls(channel=channel, params=params, timestamp=data.get("timestamp"))
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert the ChannelStepMeta to a dictionary representation.
        """
        return {
            "channel": self.channel,
            **self.params,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True, frozen=True)
class StepsMetadata:
    """
    Metadata container for workflow steps.
    """
    step_name: StepName
    created_by: str
    version: str | None = None
    timestamp: str | None = None
    # Placeholder for params when channels specific has no meaning, scope = 'all'
    params: Mapping[str, Any] = field(default_factory=dict)
    # Placeholder for channel-specific metadata, scope = Sequence[int]
    channels: Mapping[str, ChannelStepMeta] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        if self.version is None:
            object.__setattr__(self, "version", _get_dist_version(self.created_by))
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", _utc_now())
        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "channels", dict(self.channels))  # Ensure channels is a dict
    
    @classmethod
    def create(cls, 
               *, 
               step_name: StepName, 
               created_by: str, 
               exported_channel: ChannelScope = None,
               params: Mapping[str, Any] | None = None,
               ) -> StepsMetadata:
        """
        Create metadata for a workflow step.

        The storage location of ``params`` depends on ``exported_channel``:

        - None: no metadata is recorded.
        - "all": params are stored once at the step level.
        - Sequence[int]: params are stored for each exported channel.
        """ 
        params, channels = cls._build_metadata(exported_channel=exported_channel,
                                       params=params,) 
        return cls(step_name=step_name, 
                   created_by=created_by, 
                   params=params,
                   channels=channels,)
    
    @staticmethod
    def _build_metadata(exported_channel: ChannelScope, params: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, ChannelStepMeta]]:
        """
        Build metadata according to the exported channel scope. Returns a tuple of (shared_params, channel_metadata_dict).
        If exported_channel is 'all', shared_params will contain the provided params and channel_metadata_dict will be empty.
        If exported_channel is a sequence of integers, shared_params will be empty and channel_metadata_dict will contain ChannelStepMeta for each channel with the provided params.
        If exported_channel is None, both shared_params and channel_metadata_dict will be empty.
        """ 
        if exported_channel is None: 
            return {}, {} 
        
        params = dict(params or {}) 
        
        if exported_channel == 'all':
            return params, {}  # No channel-specific metadata, all channels share the same params
        
        channels: dict[str, ChannelStepMeta] = {} 
        for channel in exported_channel: 
            if channel < 0: 
                raise ValueError(f"Channel index must be non-negative, got {channel}.") 
            channels[str(channel)] = ChannelStepMeta(channel=channel, params=params,) 
        return {}, channels # No shared params, channel-specific metadata created for each channel
    
    def with_params(self,
                  exported_channel: ChannelScope = None,
                  params: Mapping[str, Any] | None = None,
                  ) -> StepsMetadata:
        """ 
        Return a copy with metadata added or replaced for selected channels. Existing metadata for other channels is preserved. 
        """ 
        params, channel_updates = self._build_metadata(exported_channel=exported_channel,
                                               params=params) 
        if not params and not channel_updates: 
            return self
        merged_params = dict(self.params)
        merged_params.update(params)
        merged_channels = dict(self.channels) 
        merged_channels.update(channel_updates) 
        return replace(self, params=merged_params, channels=merged_channels, timestamp=_utc_now(),)
    
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StepsMetadata:
        """
        Create a StepsMetadata instance from a dictionary representation.
        """
        try: 
            step_name = StepName(data["step_name"]) 
        except KeyError as exc: 
            raise ValueError("Step metadata is missing the 'step_name' field.") from exc
        
        created_by = data.get("created_by")
        if not isinstance(created_by, str) or not created_by: 
            raise ValueError("Step metadata must contain a non-empty 'created_by' field.")
        
        params = data.get("params", {})
        if not isinstance(params, Mapping):
            raise TypeError("Step metadata 'params' must be a mapping.")
        
        channels_data = data.get("channels", {})
        if not isinstance(channels_data, Mapping): 
            raise TypeError("Step metadata 'channels' must be a mapping.")
        
        channels = {str(key): ChannelStepMeta.from_dict(value) 
                    for key, value in channels_data.items() if isinstance(value, Mapping)}
        
        return cls(step_name=step_name,
                   created_by=created_by,
                   version=data.get("version"),
                   timestamp=data.get("timestamp"),
                   params=params,
                   channels=channels)
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert the StepsMetadata to a dictionary representation.
        """
        
        channels_meta = {k: v.to_dict() for k, v in self.channels.items()}
        
        return {
            "step_name": self.step_name,
            "created_by": self.created_by,
            "version": self.version,
            "timestamp": self.timestamp,
            "params": dict(self.params),
            "channels": channels_meta,
        }


@dataclass(slots=True, frozen=True)
class FitsMeta:
    """
    Metadata container for FITS files.
    """
    _run: RunMetadata = field(default_factory=RunMetadata)
    _steps: dict[StepName, StepsMetadata] = field(default_factory=dict)
    
    def __post_init__(self) -> None: 
        # Prevent an externally owned dictionary from being mutated underneath this frozen object. 
        object.__setattr__(self, "_steps", dict(self._steps))
    
    @classmethod
    def init(cls,
             *,
             user_name: str | None = None,
             created_by: str = DIST_FITS,
             ) -> FitsMeta:
        """
        Create a new FITS metadata container for a pipeline run.

        Parameters
        ----------
        user_name:
            Name of the user executing the pipeline.
        created_by:
            Distribution creating the metadata. Defaults to FITS.
        """
        return cls(_run=RunMetadata(created_by=created_by,
                                    user_name=user_name,))
    
    @property
    def run(self) -> RunMetadata:
        """
        Return the run-level metadata.
        """
        return self._run
    
    @property
    def steps(self) -> dict[StepName, StepsMetadata]:
        """
        Return the steps-level metadata.
        """
        return self._steps
    
    def with_step(self,
                  step_name: StepName,
                  created_by: str,
                  exported_channel: ChannelScope = None,
                  params: Mapping[str, Any] | None = None,
                  ) -> FitsMeta:
        """ 
        Return a copy containing metadata for a workflow step. 
        A new ``StepsMetadata`` instance is created when the step is recorded for the first time. Otherwise, metadata for the selected channels is merged into the existing step. 
        """
        steps_map = dict(self._steps)
        
        current_step = steps_map.get(step_name)
        
        if current_step is None:
            updated_step = StepsMetadata.create(step_name=step_name,
                                                created_by=created_by,
                                                exported_channel=exported_channel,
                                                params=params,)
        else:
            if current_step.created_by != created_by:
                raise ValueError(f"Step '{step_name}' was previously created by '{current_step.created_by}', cannot add metadata from '{created_by}'.")
            updated_step = current_step.with_params(exported_channel=exported_channel,
                                                     params=params,)
        steps_map[step_name] = updated_step
        return replace(self, _steps=steps_map)

    def completed_channels(self, step_name: StepName) -> list[int]:
        """
        Return processed source channel indices for a workflow step.
        """
        step_meta = self._steps.get(step_name)
        if step_meta is None:
            return []
        return [channel_meta.channel for channel_meta in step_meta.channels.values()]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FitsMeta:
        """
        Create a FitsMeta instance from a dictionary representation.
        """
        run_data = data.get("pipeline_meta", {})
        if not isinstance(run_data, Mapping): 
            raise TypeError("'pipeline_meta' must be a mapping.")
        
        steps_data = data.get("steps", {})
        if not isinstance(steps_data, Mapping): 
            raise TypeError("'steps' must be a mapping.")
        
        run_meta = RunMetadata.from_dict(run_data)
        
        steps_metadata: dict[StepName, StepsMetadata] = {} 
        for key, value in steps_data.items(): 
            if not isinstance(value, Mapping): 
                raise TypeError(f"Metadata for step {key!r} must be a mapping.") 
            
            step_name = StepName(key) 
            step_meta = StepsMetadata.from_dict(value) 
            
            if step_meta.step_name != step_name: 
                raise ValueError(f"Step key {key!r} does not match the embedded step name {step_meta.step_name.value!r}.")
            steps_metadata[step_name] = step_meta
        
        return cls(_run=run_meta, 
                   _steps=steps_metadata)
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert the FitsMeta to a dictionary representation.
        """
        return {
            "pipeline_meta": self._run.to_dict(),
            "steps": {k: v.to_dict() for k, v in self._steps.items()},
        }
