from collections.abc import Mapping, Sequence
from typing import Any


def build_channel_metadata(source_channel_indices: Sequence[int], step_meta: Mapping[str, Any]) -> dict[str, Any]:
    channels: dict[str, dict[str, Any]] = {}
    for source_channel_index in source_channel_indices:
        channels[str(source_channel_index)] = dict(step_meta)
    return {"channels": channels}
