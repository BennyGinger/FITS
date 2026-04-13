from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def merge_step_metadata(existing_step_meta: Any, update_meta: Mapping[str, Any]) -> dict[str, Any]:
    """Merge step metadata while preserving nested per-channel metadata updates."""
    out = dict(existing_step_meta) if isinstance(existing_step_meta, Mapping) else {}

    for key, value in update_meta.items():
        if key == "channels" and isinstance(value, Mapping):
            existing_channels = out.get("channels")
            merged_channels = dict(existing_channels) if isinstance(existing_channels, Mapping) else {}
            for channel_name, channel_meta in value.items():
                current_channel = merged_channels.get(channel_name)
                if isinstance(current_channel, Mapping) and isinstance(channel_meta, Mapping):
                    merged_channels[channel_name] = {**dict(current_channel), **dict(channel_meta)}
                elif isinstance(channel_meta, Mapping):
                    merged_channels[channel_name] = dict(channel_meta)
                else:
                    merged_channels[channel_name] = channel_meta
            out["channels"] = merged_channels
        else:
            out[key] = value

    return out
