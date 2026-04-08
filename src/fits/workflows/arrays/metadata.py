from collections.abc import Mapping, Sequence
from typing import Any

from fits_io.client import FitsIO


# ------ Public API -------

def labels_to_src_indices(reader: FitsIO, chan_seg: Sequence[str]) -> list[int]:
    """
    Resolve the source channel indices corresponding to the requested process of channel labels. The source channel indices are needed to identify which channels in the input TIFF should be used as sources for the given task.
    """
    exported_labels, src_chan_idxs = _get_channel_identity(reader)

    out_src_chan_idxs: list[int] = []
    for label in chan_seg:
        if label not in exported_labels:
            raise ValueError(f"Requested task label {label!r} was not found in exported TIFF channel labels {exported_labels}.")
        exported_index = exported_labels.index(label)
        out_src_chan_idxs.append(src_chan_idxs[exported_index])
    return out_src_chan_idxs


def build_channel_metadata(source_channel_indices: Sequence[int], step_meta: Mapping[str, Any]) -> dict[str, Any]:
    channels: dict[str, dict[str, Any]] = {}
    for source_channel_index in source_channel_indices:
        channels[str(source_channel_index)] = dict(step_meta)
    return {"channels": channels}


def src_indices_to_labels(reader: FitsIO, source_indices: Sequence[int]) -> list[str]:
    """
    Inverse of resolve_source_channel_indices: map source channel indices back to their export labels.
    """
    exported_labels, src_chan_idxs = _get_channel_identity(reader)
    index_to_label = {idx: label for idx, label in zip(src_chan_idxs, exported_labels)}
    result: list[str] = []
    for source_idx in source_indices:
        if source_idx not in index_to_label:
            raise ValueError(f"Source index {source_idx} not found in image source channel indices {src_chan_idxs}.")
        result.append(index_to_label[source_idx])
    return result


# ------ Helpers -------

def _get_exported_labels(reader: FitsIO) -> list[str]:
    exported_labels = reader.channel_labels
    if exported_labels is None:
        raise ValueError("Input TIFF has no channel labels.")
    return list(exported_labels)


def _get_channel_identity(reader: FitsIO) -> tuple[list[str], list[int]]:
    exported_labels = _get_exported_labels(reader)
    source_channel_indices = _get_source_channel_indices(reader)
    if len(exported_labels) != len(source_channel_indices):
        raise ValueError(f"Input TIFF metadata mismatch: channel_labels has {len(exported_labels)} entries but source_channel_indices has {len(source_channel_indices)}.")
    return exported_labels, source_channel_indices


def _get_source_channel_indices(reader: FitsIO) -> list[int]:
    raw_source_channel_indices = reader.fits_metadata.get("source_channel_indices")
    if raw_source_channel_indices is None:
        raise ValueError("Input TIFF metadata is missing source_channel_indices.")
    if isinstance(raw_source_channel_indices, (str, bytes)) or not isinstance(raw_source_channel_indices, Sequence):
        raise ValueError("Input TIFF metadata field source_channel_indices must be a sequence of integers.")
    return [int(index) for index in raw_source_channel_indices]

