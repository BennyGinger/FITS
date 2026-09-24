"""Workflow-step and per-channel provenance metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from fits.environment.constant import ChannelScope, StepName
from fits.workflows.metadata._values import distribution_version, utc_now


@dataclass(slots=True, frozen=True)
class ChannelStepMeta:
    """
    Record parameters applied to one exported channel during a step.
    """
    channel: int
    params: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", utc_now())
        object.__setattr__(self, "params", dict(self.params))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, key: str | None = None) -> ChannelStepMeta:
        """
        Create channel metadata from its serialized representation.
        """
        channel = data.get("channel")
        legacy_channel_label = None
        if (not isinstance(channel, int) or channel < 0) and key is not None:
            try:
                key_channel = int(key)
            except (TypeError, ValueError):
                key_channel = -1
            if key_channel >= 0:
                legacy_channel_label = channel
                channel = key_channel
        if not isinstance(channel, int) or channel < 0:
            raise ValueError("Channel step metadata must contain a non-negative integer "
                            "'channel' field.")
        params = {key: value for key, value in data.items()
                    if key not in ("channel", "timestamp")}
        if isinstance(legacy_channel_label, str) and legacy_channel_label:
            params.setdefault("channel_label", legacy_channel_label)
        return cls(channel=channel, params=params, timestamp=data.get("timestamp"))

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize the channel metadata.
        """
        params = dict(self.params)
        parameter_channel = params.pop("channel", None)
        if isinstance(parameter_channel, str) and parameter_channel:
            params.setdefault("channel_label", parameter_channel)
        return {**params,
                "channel": self.channel,
                "timestamp": self.timestamp,}


@dataclass(slots=True, frozen=True)
class StepMetadata:
    """
    Record provenance and shared or per-channel parameters for one step.
    """
    step_name: StepName
    created_by: str
    version: str | None = None
    timestamp: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    channels: Mapping[str, ChannelStepMeta] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.version is None:
            object.__setattr__(self, "version", distribution_version(self.created_by))
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", utc_now())
        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "channels", dict(self.channels))

    @classmethod
    def create(cls,
                *,
                step_name: StepName,
                created_by: str,
                exported_channel: ChannelScope = None,
                params: Mapping[str, Any] | None = None,
                ) -> StepMetadata:
        """
        Create metadata scoped to all, selected, or no exported channels.
        """
        shared_params, channels = cls._build_metadata(exported_channel=exported_channel,
                                                      params=params)
        return cls(step_name=step_name,
                    created_by=created_by,
                    params=shared_params,
                    channels=channels,)

    @staticmethod
    def _build_metadata(exported_channel: ChannelScope, 
                        params: Mapping[str, Any] | None,
                        ) -> tuple[dict[str, Any], dict[str, ChannelStepMeta]]:
        """
        Build shared or channel-specific parameter storage for a scope.
        """
        if exported_channel is None:
            return {}, {}
        params = dict(params or {})
        if exported_channel == "all":
            return params, {}
        channels: dict[str, ChannelStepMeta] = {}
        for channel in exported_channel:
            if channel < 0:
                raise ValueError(f"Channel index must be non-negative, got {channel}.")
            channels[str(channel)] = ChannelStepMeta(
                channel=channel, params=params)
        return {}, channels

    def with_params(self,
                    exported_channel: ChannelScope = None,
                    params: Mapping[str, Any] | None = None,
                    ) -> StepMetadata:
        """
        Add parameters while preserving metadata for unaffected channels.
        """
        shared_updates, channel_updates = self._build_metadata(
            exported_channel=exported_channel, params=params)
        if not shared_updates and not channel_updates:
            return self
        merged_params = dict(self.params)
        merged_params.update(shared_updates)
        merged_channels = dict(self.channels)
        merged_channels.update(channel_updates)
        return replace(self,
                        params=merged_params,
                        channels=merged_channels,
                        timestamp=utc_now(),)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StepMetadata:
        """
        Create step metadata from its serialized representation.
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
        
        channels = {str(key): ChannelStepMeta.from_dict(value, key=str(key))
                    for key, value in channels_data.items()
                    if isinstance(value, Mapping)}
        return cls(step_name=step_name,
                    created_by=created_by,
                    version=data.get("version"),
                    timestamp=data.get("timestamp"),
                    params=params,
                    channels=channels,)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize the step metadata.
        """
        return {"step_name": self.step_name,
                "created_by": self.created_by,
                "version": self.version,
                "timestamp": self.timestamp,
                "params": dict(self.params),
                "channels": {key: value.to_dict() for key, value in self.channels.items()},}
