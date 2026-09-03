"""Persistence helpers for ordered channel-selective ROI-state artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fits_io import FitsIO
from numpy.typing import NDArray

from fits.environment.constant import FITS_ROI_TEMPLATE
from fits.tasks.reference_mask.artifact import (
    merge_reference_channels,
    validate_reference_label,
)

ROI_MASK_ENCODING = "ordered-threshold-manual-v2"
ROI_MASK_VALUE_TABLE = {
    "0": {"threshold": "excluded", "manual": "none", "final": "excluded"},
    "1": {"threshold": "excluded", "manual": "excluded", "final": "excluded"},
    "2": {"threshold": "included", "manual": "excluded", "final": "excluded"},
    "3": {"threshold": "excluded", "manual": "included", "final": "included"},
    "4": {"threshold": "included", "manual": "none", "final": "included"},
    "5": {"threshold": "included", "manual": "included", "final": "included"},
}


def build_roi_path(source_path: Path, label: str) -> Path:
    return source_path.with_name(
        FITS_ROI_TEMPLATE.format(label=validate_reference_label(label)))


def saved_roi_channels(path: Path) -> tuple[str, ...]:
    return tuple(FitsIO.from_path(path).channel_labels) if path.is_file() else ()


def load_roi_artifact(roi_path: str | Path, *, source_path: Path,
                      source_axes: str, source_shape: tuple[int, ...],
                      source_channels: tuple[str, ...],
                      ) -> tuple[NDArray[np.uint8], str, tuple[str, ...]]:
    path = Path(roi_path).expanduser().resolve()
    prefix, suffix = FITS_ROI_TEMPLATE.split("{label}")
    if (not path.is_file() or path.parent != source_path.parent
            or not path.name.startswith(prefix) or not path.name.endswith(suffix)):
        raise ValueError(
            f"ROI mask must be an existing {prefix}*{suffix} file beside the source image.")
    label = validate_reference_label(path.name[len(prefix):len(path.name) - len(suffix)])
    reader = FitsIO.from_path(path)
    loaded = reader.get_array()
    array = np.asarray(loaded.array)
    axes = loaded.axes
    channels = tuple(reader.channel_labels)
    encoding = getattr(reader, "fits_metadata", {}).get("roi_mask_encoding")
    array = _normalize_roi_encoding(array, encoding=encoding)
    expected = tuple(size for axis, size in zip(source_axes, source_shape, strict=True)
                     if axis != "C")
    actual = tuple(size for axis, size in zip(axes, array.shape, strict=True)
                   if axis != "C")
    if axes.replace("C", "") != source_axes.replace("C", "") or actual != expected:
        raise ValueError("ROI mask axes and shape must match the source outside channels.")
    mask = np.zeros(source_shape, dtype=np.uint8)
    for index, channel in enumerate(channels):
        if channel not in source_channels:
            raise ValueError(f"ROI channel {channel!r} is not present in the source.")
        channel_mask = np.take(array, index, axis=axes.index("C")) if "C" in axes else array
        if "C" in source_axes:
            selection: list[int | slice] = [slice(None)] * mask.ndim
            selection[source_axes.index("C")] = source_channels.index(channel)
            mask[tuple(selection)] = channel_mask
        else:
            mask[...] = channel_mask
    return mask, label, channels


def merge_roi_channels(output_path: Path, channel_mask: NDArray[np.uint8], *,
                       channel_axes: str, source_axes: str,
                       channel_label: str, overwrite: bool,
                       ) -> tuple[NDArray[np.uint8], list[str]]:
    """Merge current-format channels or replace an incompatible ROI artifact."""
    if output_path.is_file():
        reader = FitsIO.from_path(output_path)
        encoding = getattr(reader, "fits_metadata", {}).get("roi_mask_encoding")
        if encoding != ROI_MASK_ENCODING:
            return channel_mask, [channel_label]

    def normalize_existing(array: NDArray[np.generic], reader: object,
                           ) -> NDArray[np.uint8]:
        metadata = getattr(reader, "fits_metadata", {})
        return _normalize_roi_encoding(
            array, encoding=metadata.get("roi_mask_encoding"))

    return merge_reference_channels(
        output_path, channel_mask, channel_axes=channel_axes,
        source_axes=source_axes, channel_label=channel_label,
        overwrite=overwrite, artifact_label="ROI",
        existing_array_transform=normalize_existing)


def _normalize_roi_encoding(array: NDArray[np.generic], *,
                            encoding: object) -> NDArray[np.uint8]:
    """Validate the current ordered ROI encoding without guessing formats."""
    if encoding != ROI_MASK_ENCODING:
        raise ValueError(
            f"ROI mask encoding must be {ROI_MASK_ENCODING!r}; got {encoding!r}.")
    values = np.asarray(array)
    if not np.all(np.isin(values, (0, 1, 2, 3, 4, 5))):
        raise ValueError("Loaded ROI mask contains invalid ordered ROI states.")
    return values.astype(np.uint8, copy=False)
