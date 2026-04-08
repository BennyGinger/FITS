from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar
from math import prod

import numpy as np
from numpy.typing import NDArray

from fits.workflows.arrays.validations import validate_axis_order


T = TypeVar("T", bound=np.generic)

@dataclass(frozen=True)
class FlatFrameBatch:
    frames: list[NDArray[Any]]
    axis_order: str
    original_shape: tuple[int, ...]
    moved_shape: tuple[int, ...]
    batch_shape: tuple[int, ...]
    yx_shape: tuple[int, int]
    spatial_indices: tuple[int, int]

    def rebuild(self, frames: list[NDArray[T]]) -> NDArray[T]:
        expected_count = prod(self.batch_shape) if self.batch_shape else 1
        if len(frames) != expected_count:
            raise ValueError(f"Expected {expected_count} frame(s), got {len(frames)}.")

        for i, frame in enumerate(frames):
            if not isinstance(frame, np.ndarray):
                raise ValueError(f"frames[{i}] must be a numpy.ndarray, got {type(frame).__name__}.")
            if frame.shape != self.yx_shape:
                raise ValueError(f"frames[{i}] has shape {frame.shape}, expected {self.yx_shape}.")

        flat = np.stack(frames, axis=0)
        moved = flat.reshape(self.moved_shape)
        y_idx, x_idx = self.spatial_indices
        rebuilt = np.moveaxis(moved, (-2, -1), (y_idx, x_idx))

        if tuple(rebuilt.shape) != self.original_shape:
            raise ValueError(f"Rebuilt shape {tuple(rebuilt.shape)} does not match original shape {self.original_shape}.")

        return rebuilt


def flatten_to_frames(array: NDArray[Any], axis_order: str) -> FlatFrameBatch:
    validate_axis_order(array, axis_order)
    y_idx, x_idx = _get_spatial_indices(axis_order)

    moved = np.moveaxis(array, (y_idx, x_idx), (-2, -1))
    moved_shape = tuple(moved.shape)
    batch_shape = tuple(moved.shape[:-2])
    yx_shape = (moved.shape[-2], moved.shape[-1])

    flat = moved.reshape(-1, *yx_shape)
    frames = [flat[i] for i in range(flat.shape[0])]

    return FlatFrameBatch(
        frames=frames,
        axis_order=axis_order,
        original_shape=tuple(array.shape),
        moved_shape=moved_shape,
        batch_shape=batch_shape,
        yx_shape=yx_shape,
        spatial_indices=(y_idx, x_idx),
    )


def _get_spatial_indices(axis_order: str) -> tuple[int, int]:
    return axis_order.index("Y"), axis_order.index("X")