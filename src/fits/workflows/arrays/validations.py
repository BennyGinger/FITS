from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray


def validate_no_duplicate_axes(axes: str) -> None:
    """Raise ValueError if axes contains duplicate dimension characters."""
    if len(set(axes)) != len(axes):
        raise ValueError(f"Axes string contains duplicate dimensions: {axes!r}")


def validate_axes_rank(array: NDArray[Any], axes: str, *, label: str = "Array") -> None:
    """Raise ValueError if len(axes) does not match array.ndim."""
    if len(axes) != array.ndim:
        raise ValueError(f"{label} axes {axes!r} do not match array shape {array.shape}.")


def validate_axis_order(array: np.ndarray, axis_order: str) -> None:
    """Validate that axis_order is a string compatible with array: correct rank, no duplicates, exactly one Y and one X."""
    if not isinstance(array, np.ndarray):
        raise ValueError(f"array must be a numpy.ndarray, got {type(array).__name__}.")
    if not isinstance(axis_order, str):
        raise ValueError(f"axis_order must be a string, got {type(axis_order).__name__}.")
    validate_axes_rank(array, axis_order, label="axis_order")
    validate_no_duplicate_axes(axis_order)
    y_count = axis_order.count("Y")
    x_count = axis_order.count("X")
    if y_count != 1:
        raise ValueError(f"axis_order must contain exactly one 'Y' axis, found {y_count} in {axis_order!r}.")
    if x_count != 1:
        raise ValueError(f"axis_order must contain exactly one 'X' axis, found {x_count} in {axis_order!r}.")


def validate_channel_count(array: NDArray[Any], axes: str, source_indices: Sequence[int]) -> None:
    """Raise ValueError if the C-axis size does not match the number of source channel indices."""
    if 'C' in axes:
        c_ax = axes.find('C')
        if array.shape[c_ax] != len(source_indices):
            raise ValueError(f"Array has {array.shape[c_ax]} channel(s) but {len(source_indices)} source channel indices were provided.")
    elif len(source_indices) != 1:
        raise ValueError(f"Array has no C axis but {len(source_indices)} source channel indices were provided (expected 1).")


def validate_mask_output(array: Any, axes: str, channel_labels: list[str]) -> None:
    """Raise ValueError if axes/shape/channel-labels are mutually inconsistent for a merged mask output."""
    if len(axes) != array.ndim:
        raise ValueError(f"Merged mask output is inconsistent: axes={axes!r}, shape={array.shape}")
    c_ax = axes.find('C')
    if c_ax != -1 and array.shape[c_ax] != len(channel_labels):
        raise ValueError(f"Merged mask labels do not match channel axis: axes={axes!r}, shape={array.shape}, labels={channel_labels}")
