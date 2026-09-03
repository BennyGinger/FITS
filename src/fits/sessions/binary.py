from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
from mask_interpolation import fill_missing_masks
from numpy.typing import NDArray

from fits.sessions.image import FitsImageSession


class BinaryMaskSession(FitsImageSession):
    """Shared in-memory editing mechanics for source-shaped binary masks."""

    def __init__(self, source_path: str | Path) -> None:
        super().__init__(source_path)
        self._mask = np.zeros(self._array.shape, dtype=np.uint8)

    @property
    def mask_array(self) -> NDArray[np.uint8]:
        return self._mask.copy()

    def mask_plane(self, frame_index: int = 0, channel: int | str = 0,
                   z_index: int = 0) -> NDArray[np.uint8]:
        return self._select_plane(
            self._mask, frame_index=frame_index,
            channel=channel, z_index=z_index).copy()

    def set_mask_plane(self, mask: NDArray[np.generic], *,
                       frame_index: int = 0, channel: int | str = 0,
                       z_index: int = 0) -> None:
        expected_shape = (
            self._array.shape[self._axes.index("Y")],
            self._array.shape[self._axes.index("X")],)
        if mask.shape != expected_shape:
            raise ValueError(
                f"Mask plane shape {mask.shape} does not match image plane "
                f"shape {expected_shape}.")
        if not np.all((mask == 0) | (mask == 1)):
            raise ValueError("Mask planes must be binary with values 0 and 1.")
        self._mask[self._plane_selection(frame_index, channel, z_index)] = (
            mask.astype(np.uint8, copy=False))

    def clear_mask_plane(self, *, frame_index: int = 0,
                         channel: int | str = 0, z_index: int = 0) -> None:
        self._mask[self._plane_selection(frame_index, channel, z_index)] = 0

    def completed_mask(self, interpolation_axis: str, *,
                       extrapolate_start: bool = True,
                       extrapolate_end: bool = True) -> NDArray[np.uint8]:
        return cast(NDArray[np.uint8], fill_missing_masks(
            self._mask, axes=self._axes,
            interpolation_axis=interpolation_axis,
            extrapolate_start=extrapolate_start,
            extrapolate_end=extrapolate_end))

    def _channel_mask(self, channel_index: int) -> NDArray[np.uint8]:
        if "C" not in self._axes:
            return self.mask_array
        return np.take(self._mask, channel_index, axis=self._axes.index("C")).copy()
