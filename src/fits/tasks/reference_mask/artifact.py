"""Loading, validation and channel merging for reference-mask artifacts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from fits_io import FitsIO
from numpy.typing import NDArray

from fits.environment.constant import FITS_REFERENCE_TEMPLATE


_WINDOWS_INVALID_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')


def validate_reference_label(label: str) -> str:
    """
    Validate and normalize a portable reference-mask filename label.
    """
    if not isinstance(label, str):
        raise TypeError("Reference-mask label must be a string.")
    normalized = label.strip()
    if not normalized:
        raise ValueError("Reference-mask label cannot be empty.")
    if normalized.endswith("."):
        raise ValueError("Reference-mask label cannot end with a period.")
    invalid = _WINDOWS_INVALID_FILENAME_CHARACTERS.intersection(normalized)
    if invalid or any(ord(character) < 32 for character in normalized):
        raise ValueError(
            f"Reference-mask label contains invalid filename characters: {label!r}.")
    return normalized


def build_reference_path(source_path: Path, label: str) -> Path:
    """
    Build the reference-artifact path beside its normalized source image.
    """
    normalized_label = validate_reference_label(label)
    return source_path.with_name(
        FITS_REFERENCE_TEMPLATE.format(label=normalized_label))


def saved_reference_channels(path: Path) -> tuple[str, ...]:
    """
    Return channel labels stored in an existing reference artifact.
    """
    if not path.is_file():
        return ()
    return tuple(FitsIO.from_path(path).channel_labels)


def load_reference_artifact(reference_path: str | Path,
                            *,
                            source_path: Path,
                            source_axes: str,
                            source_shape: tuple[int, ...],
                            source_channels: tuple[str, ...],
                            ) -> tuple[NDArray[np.uint8], str, tuple[str, ...]]:
    """
    Load a compact reference artifact into a source-shaped binary array.
    """
    path, label = _validate_reference_path(reference_path, source_path)
    reference_reader = FitsIO.from_path(path)
    loaded = reference_reader.get_array()
    reference = np.asarray(loaded.array)
    reference_axes = loaded.axes
    reference_channels = tuple(reference_reader.channel_labels)
    _validate_reference_array(
        reference,
        reference_axes=reference_axes,
        source_axes=source_axes,
        source_shape=source_shape,)

    mask = np.zeros(source_shape, dtype=np.uint8)
    for reference_index, channel_label in enumerate(reference_channels):
        try:
            source_index = source_channels.index(channel_label)
        except ValueError as error:
            raise ValueError(
                f"Reference channel {channel_label!r} is not present in the "
                f"source channels {source_channels}.") from error
        channel_mask = (np.take(reference, reference_index, axis=reference_axes.index("C"))
                        if "C" in reference_axes
                        else reference)
        if "C" in source_axes:
            selection: list[int | slice] = [slice(None)] * mask.ndim
            selection[source_axes.index("C")] = source_index
            mask[tuple(selection)] = channel_mask
        else:
            mask[...] = channel_mask
    return mask, label, reference_channels


def merge_reference_channels(output_path: Path,
                             channel_mask: NDArray[np.uint8],
                             *,
                             channel_axes: str,
                             source_axes: str,
                             channel_label: str,
                             overwrite: bool,
                             artifact_label: str = "Reference",
                             existing_array_transform: Callable[
                                 [NDArray[np.generic], Any], NDArray[np.generic]
                             ] | None = None,
                             ) -> tuple[NDArray[np.uint8], list[str]]:
    """
    Append or replace one channel in a compact reference artifact array.
    """
    if not output_path.is_file():
        return channel_mask, [channel_label]

    existing_reader = FitsIO.from_path(output_path)
    existing = existing_reader.get_array()
    existing_array = np.asarray(existing.array)
    if existing_array_transform is not None:
        existing_array = existing_array_transform(existing_array, existing_reader)
    existing_array = np.asarray(existing_array, dtype=np.uint8)
    existing_axes = existing.axes
    existing_labels = list(existing_reader.channel_labels)
    if existing_axes.replace("C", "") != channel_axes:
        raise ValueError(
            f"Existing {artifact_label.lower()} axes {existing_axes!r} do not match "
            f"the current channel axes {channel_axes!r}.")

    channel_position = source_axes.index("C") if "C" in source_axes else 0
    existing_stack = (existing_array
                      if "C" in existing_axes
                      else np.expand_dims(existing_array, axis=channel_position))
    populated = [
        index for index in range(existing_stack.shape[channel_position])
        if np.any(np.take(existing_stack, index, axis=channel_position))]
    existing_stack = np.take(existing_stack, populated, axis=channel_position)
    existing_labels = [existing_labels[index] for index in populated]
    if channel_label in existing_labels and not overwrite:
        raise FileExistsError(
            f"{artifact_label} channel {channel_label!r} already exists in {output_path}.")

    current_stack = np.expand_dims(channel_mask, axis=channel_position)
    if channel_label in existing_labels:
        selection: list[int | slice] = [slice(None)] * existing_stack.ndim
        selection[channel_position] = existing_labels.index(channel_label)
        existing_stack[tuple(selection)] = channel_mask
        return _compact_channel_axis(existing_stack, existing_labels, channel_position)

    merged = np.concatenate((existing_stack, current_stack), axis=channel_position)
    return _compact_channel_axis(
        merged, [*existing_labels, channel_label], channel_position)


def _validate_reference_path(reference_path: str | Path,
                             source_path: Path,
                             ) -> tuple[Path, str]:
    path = Path(reference_path).expanduser().resolve()
    prefix, suffix = FITS_REFERENCE_TEMPLATE.split("{label}")
    if (not path.is_file()
            or path.parent != source_path.parent
            or not path.name.startswith(prefix)
            or not path.name.endswith(suffix)):
        raise ValueError(
            f"Reference mask must be an existing {prefix}*{suffix} file "
            "beside the source image.")
    label = path.name[len(prefix):len(path.name) - len(suffix)]
    return path, validate_reference_label(label)


def _validate_reference_array(reference: NDArray[np.generic],
                              *,
                              reference_axes: str,
                              source_axes: str,
                              source_shape: tuple[int, ...],
                              ) -> None:
    if not np.all((reference == 0) | (reference == 1)):
        raise ValueError("Loaded reference masks must contain only binary values 0 and 1.")
    if reference_axes.replace("C", "") != source_axes.replace("C", ""):
        raise ValueError(
            f"Reference axes {reference_axes!r} do not match source axes {source_axes!r}.")
    expected_shape = tuple(
        size for axis, size in zip(source_axes, source_shape, strict=True)
        if axis != "C")
    reference_shape = tuple(
        size for axis, size in zip(reference_axes, reference.shape, strict=True)
        if axis != "C")
    if reference_shape != expected_shape:
        raise ValueError(
            f"Reference shape {reference.shape} does not match source shape "
            f"{source_shape} outside the channel axis.")


def _compact_channel_axis(array: NDArray[np.uint8],
                          labels: list[str],
                          channel_position: int,
                          ) -> tuple[NDArray[np.uint8], list[str]]:
    output = (np.take(array, 0, axis=channel_position)
              if len(labels) == 1
              else array)
    return output, labels
