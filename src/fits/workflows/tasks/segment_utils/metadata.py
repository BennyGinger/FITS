from collections.abc import Mapping, Sequence
from typing import Any

from fits_io.client import FitsIO


def resolve_segment_source_channel_indices(reader: FitsIO, chan_seg: Sequence[str]) -> list[int]:
    exported_labels = reader.channel_labels
    if exported_labels is None:
        raise ValueError("Input TIFF has no channel labels; cannot resolve segmentation source channel indices.")

    raw_source_channel_indices = reader.fits_metadata.get("source_channel_indices")
    if raw_source_channel_indices is None:
        raise ValueError("Input TIFF metadata is missing source_channel_indices; cannot resolve stable segmentation channel identity.")
    if isinstance(raw_source_channel_indices, (str, bytes)) or not isinstance(raw_source_channel_indices, Sequence):
        raise ValueError("Input TIFF metadata field source_channel_indices must be a sequence of integers.")

    source_channel_indices = [int(index) for index in raw_source_channel_indices]
    if len(exported_labels) != len(source_channel_indices):
        raise ValueError(f"Input TIFF metadata mismatch: channel_labels has {len(exported_labels)} entries but source_channel_indices has {len(source_channel_indices)}.")

    segmented_source_channel_indices: list[int] = []
    for label in chan_seg:
        if label not in exported_labels:
            raise ValueError(f"Requested segmentation label {label!r} was not found in exported TIFF channel labels {exported_labels}.")
        exported_index = exported_labels.index(label)
        segmented_source_channel_indices.append(source_channel_indices[exported_index])
    return segmented_source_channel_indices


def build_segment_channel_metadata(segmented_source_channel_indices: Sequence[int], segmentation_meta: Mapping[str, Any]) -> dict[str, Any]:
    channels: dict[str, dict[str, Any]] = {}
    for source_channel_index in segmented_source_channel_indices:
        channels[str(source_channel_index)] = dict(segmentation_meta)
    return {"channels": channels}