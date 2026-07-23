# from __future__ import annotations

# from collections.abc import Sequence
# from dataclasses import dataclass
# from pathlib import Path
# from typing import Any, TypeVar

# from fits_io.client import FitsIO
# import numpy as np
# from numpy.typing import NDArray


# T = TypeVar("T", bound=np.generic)

# @dataclass(slots=True, frozen=True)
# class ChannelMergeResult:
#     array: NDArray[Any]
#     axes: str
#     channel_indices: list[int]


# def merge_channel(*,
#                 output_path: Path | None,
#                 overwrite: bool,
#                 new_array: NDArray[T],
#                 new_axes: str,
#                 new_channel_indices: Sequence[int],
#                 reference_axes: str,
#                 )-> ChannelMergeResult:
#     """
#     Merge a new channel array with an existing one, if present, and return the merged result.
    
#     Args:
#         output_path: Path to the existing artifact to merge with, or None if no existing artifact
#         overwrite: Whether to overwrite the existing artifact if it exists
#         new_array: The new channel array to merge
#         new_axes: The axes string for the new array
#         new_channel_indices: The channel indices for the new array
#         reference_axes: The reference axes string to determine the position of the channel axis
        
#     Returns:
#         A ChannelMergeResult containing the merged array, its axes, and the combined channel indices.
#     """
#     new_indices = list(new_channel_indices)
#     existing_mask_path = None if overwrite else output_path
#     if existing_mask_path is None:
#         return ChannelMergeResult(array=new_array, axes=new_axes, channel_indices=new_indices)
    
#     existing_reader = FitsIO.from_path(existing_mask_path)
#     existing_indices = existing_reader.artifact_channel_indices
    
#     if existing_indices is None:
#         raise ValueError(f"Existing artifact at {existing_mask_path} does not have channel indices metadata.")
    
#     existing_array = existing_reader.get_array().array
#     existing_axes = existing_reader.axes

#     merged_axes, c_position = _merged_axes(existing_axes=existing_axes, reference_axes=reference_axes,)
    
    
#     exist_arr_with_c = _ensure_channel_axis(array=existing_array, axes=existing_axes, c_position=c_position,)
#     new_arr_with_c = _ensure_channel_axis(array=new_array, axes=new_axes, c_position=c_position,)
    
#     merged_array = np.concatenate([exist_arr_with_c, new_arr_with_c], axis=c_position,)
    
#     return ChannelMergeResult(array=merged_array, axes=merged_axes, channel_indices=[*existing_indices, *new_indices])


# def _ensure_channel_axis(*, array: NDArray[T], axes: str, c_position: int,) -> NDArray[T]:
#     if 'C' not in axes:
#         return np.expand_dims(array, axis=c_position)
    
#     current_position = axes.index('C')
        
#     if current_position == c_position:
#         return array
    
#     return np.moveaxis(array, current_position, c_position)


# def _merged_axes(*, existing_axes: str, reference_axes: str,) -> tuple[str, int]:
    
#     if "C" in existing_axes:
#         return existing_axes, existing_axes.index("C")

#     if "C" in reference_axes:
#         c_position = reference_axes.index("C")
#     else:
#         try:
#             c_position = existing_axes.index("Y")
#         except ValueError as exc:
#             raise ValueError(f"Cannot place a channel axis in axes {existing_axes!r}: "
#                              "there is no C axis in the reference and no Y axis."
#                              ) from exc

#     merged_axes = (existing_axes[:c_position] + "C" + existing_axes[c_position:])
#     return merged_axes, c_position