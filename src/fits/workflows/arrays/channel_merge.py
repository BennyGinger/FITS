# from __future__ import annotations

# from collections.abc import Sequence
# from typing import TypeVar

# import numpy as np
# from numpy.typing import NDArray

# from fits.workflows.arrays.validations import validate_channel_labels_exist


# T = TypeVar('T', bound=np.generic)



# def resolve_excluded_channel_indices(excluded_labels: Sequence[str] | None, channel_labels: list[str] | None, *, field_name: str = "exclude_channel") -> set[int]:
#     """Resolve excluded channel labels to channel indices."""
#     if not excluded_labels:
#         return set()
#     validate_channel_labels_exist(excluded_labels, channel_labels, field_name)
#     assert channel_labels is not None
#     return {channel_labels.index(label) for label in excluded_labels}


# def included_channel_indices(channel_count: int, excluded_indices: set[int]) -> list[int]:
#     """Return included channel indices from channel count and excluded set."""
#     return [i for i in range(channel_count) if i not in excluded_indices]


# def take_channels(array: NDArray[T], axes: str, include_indices: Sequence[int]) -> NDArray[T]:
#     """Take a channel subset from an array using C-axis indices."""
#     if 'C' not in axes:
#         raise ValueError("Cannot take channel subset: array has no C axis.")
#     c_idx = axes.index('C')
#     return np.take(array, list(include_indices), axis=c_idx)


# def merge_channel_subset_back(original_array: NDArray[T], transformed_subset: NDArray[T], axes: str, include_indices: Sequence[int]) -> NDArray[T]:
#     """Merge transformed subset channels back into a copy of the original array."""
#     if 'C' not in axes:
#         raise ValueError("Cannot merge channel subset: array has no C axis.")
#     c_idx = axes.index('C')
#     output_array = np.array(original_array, copy=True)
#     moved_src = np.moveaxis(transformed_subset, c_idx, 0)
#     moved_dst = np.moveaxis(output_array, c_idx, 0)
#     for pos, original_idx in enumerate(include_indices):
#         moved_dst[original_idx] = moved_src[pos]
#     return np.moveaxis(moved_dst, 0, c_idx)

