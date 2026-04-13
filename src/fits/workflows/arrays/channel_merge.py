from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

import numpy as np
from numpy.typing import NDArray

from fits.workflows.arrays.validations import validate_axes_rank, validate_channel_count, validate_no_duplicate_axes

T = TypeVar('T', bound=np.generic)


# ── Public API ─────────────────────────────────────────────────────────────────

def merge_channel_arrays(existing_array: NDArray[T] | None, existing_axes: str | None, existing_source_indices: Sequence[int] | None, new_array: NDArray[T], new_axes: str, new_source_indices: Sequence[int], reference_axes: str) -> tuple[NDArray[T], str, list[int]]:
    """
    Merge a new per-channel result array into an existing saved artifact array.

    Channel identity is determined by *source_channel_indices*, not labels.  New
    channels replace existing ones with the same source index; all other existing
    channels are preserved.  Output channels are sorted by source channel index.

    Args:
        existing_array: Previously saved array, or None if no prior result exists.
        existing_axes: Axes string for *existing_array*; None when *existing_array* is None.
        existing_source_indices: Source channel indices for *existing_array*; None when *existing_array* is None.
        new_array: Newly produced result array to merge in.
        new_axes: Axes string for *new_array*.
        new_source_indices: Source channel indices for *new_array*.
        reference_axes: Axes string of the source image; determines channel-axis presence and 'C' position.

    Returns:
        Tuple of (merged_array, merged_axes, merged_source_channel_indices).
        *merged_source_channel_indices* is sorted and matches the channel dim ordering of *merged_array*.

    Raises:
        ValueError: On structural inconsistency such as channel count mismatches,
            incompatible non-channel shapes, or axes with duplicate dimensions.
    """
    new_norm, new_axes_norm = _ensure_channel_axis(new_array, new_axes, reference_axes)

    new_source = list(new_source_indices)
    if not new_source:
        raise ValueError("new_source_indices must not be empty.")

    validate_channel_count(new_norm, new_axes_norm, new_source)

    # No existing array: sort channels and return directly.
    if existing_array is None:
        merged_source = sorted(new_source)
        if merged_source != new_source and 'C' in new_axes_norm:
            c_ax = _channel_axis_index(new_axes_norm)
            pos_map = {si: i for i, si in enumerate(new_source)}
            perm_idx = [pos_map[si] for si in merged_source]
            new_norm = np.take(new_norm, perm_idx, axis=c_ax)
        validate_axes_rank(new_norm, new_axes_norm, label="Merged")
        return new_norm, new_axes_norm, merged_source

    # Validate existing inputs.
    if existing_axes is None or existing_source_indices is None:
        raise ValueError("existing_axes and existing_source_indices must both be provided when existing_array is not None.")
    validate_no_duplicate_axes(existing_axes)
    existing_source = list(existing_source_indices)

    existing_norm, existing_axes_norm = _ensure_channel_axis(existing_array, existing_axes, reference_axes)
    validate_channel_count(existing_norm, existing_axes_norm, existing_source)
    _validate_merge_compatibility(existing_norm, existing_axes_norm, new_norm, new_axes_norm, new_axes_norm, reference_axes)

    merged_source = _merged_channel_indices(existing_source, new_source)
    merged_array = _assemble_channel_stack(existing_norm, new_norm, existing_source, new_source, merged_source, new_axes_norm)
    validate_axes_rank(merged_array, new_axes_norm, label="Merged")
    return merged_array, new_axes_norm, merged_source


# ── Internal helpers ───────────────────────────────────────────────────────────

def _merged_channel_indices(existing: Sequence[int], new: Sequence[int]) -> list[int]:
    """
    Compute the sorted list of source channel indices that should exist after merge.

    This is simply the union of existing and new channels, sorted to ensure a
    deterministic output channel order.
    """
    return sorted(set(existing) | set(new))



def _assemble_channel_stack(existing: NDArray[T], new: NDArray[T], existing_source: Sequence[int], new_source: Sequence[int], merged_source: Sequence[int], axes: str) -> NDArray[T]:
    """
    Build the merged array by selecting channel slices from the existing or new arrays.
    """
    c_ax = _channel_axis_index(axes)
    new_map = {si: i for i, si in enumerate(new_source)}
    existing_map = {si: i for i, si in enumerate(existing_source)}
    parts = []
    for si in merged_source:
        if si in new_map:
            parts.append(np.take(new, [new_map[si]], axis=c_ax))
        else:
            parts.append(np.take(existing, [existing_map[si]], axis=c_ax))
    return np.concatenate(parts, axis=c_ax)



def _channel_axis_index(axes: str) -> int:
    """
    Return the index of the 'C' dimension in *axes*; raise if absent.
    """
    idx = axes.find('C')
    if idx == -1:
        raise ValueError(f"Axes string {axes!r} does not contain a 'C' dimension.")
    return idx


def _c_insertion_position(array_axes: str, reference_axes: str) -> int:
    """
    Compute where to insert 'C' into *array_axes* to match its position in *reference_axes*.
    """
    dims_before_c = set(reference_axes[:reference_axes.index('C')])
    return sum(1 for d in array_axes if d in dims_before_c)


def _non_channel_shape(array: NDArray[Any], axes: str) -> tuple[int, ...]:
    """
    Return the array shape with the C dimension removed.
    """
    if 'C' not in axes:
        return array.shape
    c_ax = _channel_axis_index(axes)
    return array.shape[:c_ax] + array.shape[c_ax + 1:]


def _validate_merge_compatibility(existing_norm: NDArray[Any], existing_axes_norm: str, new_norm: NDArray[Any], new_axes_norm: str, canonical: str, reference_axes: str) -> None:
    """
    Validate structural compatibility between normalized arrays before channel-wise merge.
    """
    if existing_axes_norm != new_axes_norm:
        raise ValueError(f"Incompatible axes ordering between arrays: existing={existing_axes_norm!r}, new={new_axes_norm!r}.")
    if 'C' not in canonical:
        raise ValueError(f"Cannot merge channel arrays: no 'C' dimension in canonical axes {canonical!r} derived from reference {reference_axes!r}.")
    if existing_norm.ndim != new_norm.ndim:
        raise ValueError(f"Arrays have different dimensionality after normalization: existing={existing_norm.ndim}, new={new_norm.ndim}.")
    if _non_channel_shape(existing_norm, canonical) != _non_channel_shape(new_norm, canonical):
        raise ValueError(f"Non-channel shapes are incompatible: existing={_non_channel_shape(existing_norm, canonical)}, new={_non_channel_shape(new_norm, canonical)}.")


def _ensure_channel_axis(array: NDArray[T], array_axes: str, reference_axes: str) -> tuple[NDArray[T], str]:
    """
    Insert a singleton 'C' axis when the reference has 'C' but the array does not.

    If both already contain 'C', or if the reference has no 'C', the array and axes
    are returned unchanged.

    Args:
        array: Input array to normalize.
        array_axes: Axes string for *array*.
        reference_axes: Axes string of the reference image; determines whether and where to insert 'C'.

    Returns:
        Tuple of (normalized_array, normalized_axes).
    """
    validate_no_duplicate_axes(array_axes)
    validate_no_duplicate_axes(reference_axes)
    validate_axes_rank(array, array_axes, label="Input")
    if 'C' not in reference_axes or 'C' in array_axes:
        return array, array_axes
    pos = _c_insertion_position(array_axes, reference_axes)
    expanded = np.expand_dims(array, axis=pos)
    expanded_axes = array_axes[:pos] + 'C' + array_axes[pos:]
    validate_axes_rank(expanded, expanded_axes, label="Expanded")
    return expanded, expanded_axes


# ----------- Coming from fits_io.private -------------
# def _merge_step_metadata(existing_step_meta: Any, update_meta: Mapping[str, Any]) -> dict[str, Any]:
#     merged = dict(existing_step_meta) if isinstance(existing_step_meta, Mapping) else {}

#     if 'channels' in update_meta:
#         new_channels = update_meta.get('channels')
#         if isinstance(new_channels, Mapping):
#             existing_channels = merged.get('channels')
#             merged_channels = dict(existing_channels) if isinstance(existing_channels, Mapping) else {}
#             merged_channels.update(dict(new_channels))
#             merged['channels'] = merged_channels
#         else:
#             merged['channels'] = new_channels

#     for key, value in update_meta.items():
#         if key == 'channels':
#             continue
#         merged[key] = value
#     return merged