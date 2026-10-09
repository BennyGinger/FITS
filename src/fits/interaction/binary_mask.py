from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import cast

import numpy as np
from mask_interpolation import fill_missing_masks
from numpy.typing import NDArray

from fits.interaction.image import FitsImageSession
from fits.interaction.planes import PlaneStore, disk_empty
from fits.interaction.mask_preview import MaskPreviewCache


class BinaryMaskSession(FitsImageSession):
    """
    Shared plane-based editing mechanics for source-shaped binary masks.
    """
    def __init__(self, source_path: str | Path) -> None:
        super().__init__(source_path)
        self._mask = PlaneStore(self.axes, self.shape, dtype=np.uint8)
        self.preview_cache = MaskPreviewCache(self.source_path)

    def preview_key(self, axis: str, *, frame_index: int = 0,
                    channel: int | str = 0, z_index: int = 0,
                    extrapolate_start: bool = True, extrapolate_end: bool = True) -> tuple:
        """Key one independent sequence; navigation along its axis reuses it."""
        if axis not in "TZ" or len(axis) != 1 or axis not in self.axes:
            raise ValueError("Propagation previews require a present T or Z axis.")
        return (id(self._mask), self._mask.revision, axis, self._resolve_channel(channel),
                z_index if axis == "T" else frame_index, extrapolate_start, extrapolate_end)

    def _preview_plane(self, axis: str, *, frame_index: int, channel: int | str,
                       z_index: int, extrapolate_start: bool, extrapolate_end: bool,
                       complete: Callable[[NDArray[np.uint8]], NDArray[np.uint8]],
                       cancelled: Callable[[], bool] | None = None,
                       progress: Callable[[str], None] | None = None) -> NDArray[np.uint8]:
        key = self.preview_key(axis, frame_index=frame_index, channel=channel,
                               z_index=z_index, extrapolate_start=extrapolate_start,
                               extrapolate_end=extrapolate_end)
        count = self.frame_count if axis == "T" else self.plane_count
        index = frame_index if axis == "T" else z_index
        return self.preview_cache.plane(
            key, index, count=count,
            shape=(self.shape[self.axes.index("Y")], self.shape[self.axes.index("X")]),
            read=lambda position: self.mask_plane(
                position if axis == "T" else frame_index, channel,
                z_index if axis == "T" else position), complete=complete,
            cancelled=cancelled, progress=progress)

    def _prepare_preview_sequence(self, anchors: NDArray[np.uint8],
                                  extrapolate_start: bool, extrapolate_end: bool
                                  ) -> Callable[[int], NDArray]:
        from mask_interpolation import SequenceInterpolator
        return SequenceInterpolator(anchors, extrapolate_start=extrapolate_start,
                                    extrapolate_end=extrapolate_end)

    def prepare_preview(self, axis: str, *, frame_index: int, channel: int | str,
                        z_index: int, extrapolate_start: bool, extrapolate_end: bool,
                        priority: Callable[[], int], cancelled: Callable[[], bool],
                        ready: Callable[[int], None], progress: Callable[[str], None]) -> None:
        key = self.preview_key(axis, frame_index=frame_index, channel=channel,
                               z_index=z_index, extrapolate_start=extrapolate_start,
                               extrapolate_end=extrapolate_end)
        self.preview_cache.prepare(
            key, count=self.frame_count if axis == "T" else self.plane_count,
            shape=(self.shape[self.axes.index("Y")], self.shape[self.axes.index("X")]),
            read=lambda position: self.mask_plane(
                position if axis == "T" else frame_index, channel,
                z_index if axis == "T" else position),
            prepare=lambda anchors: self._prepare_preview_sequence(
                anchors, extrapolate_start, extrapolate_end), priority=priority,
            cancelled=cancelled, ready=ready, progress=progress)

    def _completed_channel(self, channel: int, axis: str,
                           extrapolate_start: bool, extrapolate_end: bool,
                           complete: Callable[[NDArray[np.uint8]], NDArray[np.uint8]],
                           ) -> NDArray[np.uint8]:
        """Reuse completed previews; calculate only uncached independent sequences."""
        axes = self.axes.replace("C", "")
        shape = tuple(size for axis_name, size in zip(self.axes, self.shape, strict=True)
                      if axis_name != "C")
        output = disk_empty(shape, np.uint8)
        if axis not in ("T", "Z") or axis not in axes:
            raise ValueError("Propagation requires a present T or Z axis.")
        other_axis = "Z" if axis == "T" else "T"
        count = self.plane_count if axis == "T" else self.frame_count
        for position in range(count):
            selection: list[int | slice] = [slice(None)] * output.ndim
            if other_axis in axes:
                selection[axes.index(other_axis)] = position
            sequence = output[tuple(selection)]
            key = self.preview_key(
                axis, channel=channel,
                frame_index=position if axis == "Z" else 0,
                z_index=position if axis == "T" else 0,
                extrapolate_start=extrapolate_start, extrapolate_end=extrapolate_end)
            if self.preview_cache.copy_into(key, sequence):
                continue
            for index in range(len(sequence)):
                frame, z = (index, position) if axis == "T" else (position, index)
                sequence[index] = self.mask_plane(frame, channel, z)
            if np.any(sequence):
                sequence[...] = complete(sequence)
        return output

    @property
    def mask_array(self) -> NDArray[np.uint8]:
        return self._mask.copy()

    def mask_plane(self, frame_index: int = 0, channel: int | str = 0, z_index: int = 0) -> NDArray[np.uint8]:
        """
        Retrieve a specific plane from the binary mask.

        Args:
            frame_index: Index of the frame to retrieve.
            channel: Index or name of the channel to retrieve.
            z_index: Index of the Z slice to retrieve.

        Returns:
            A copy of the requested mask plane as a 2D numpy array.
        """
        self._plane_selection(frame_index, channel, z_index)
        return self._mask.plane(frame_index, self._resolve_channel(channel), z_index).copy()

    def set_mask_plane(self, mask: NDArray[np.generic], *,
                       frame_index: int = 0, channel: int | str = 0,
                       z_index: int = 0) -> None:
        """
        Set a specific plane in the binary mask.

        Args:
            mask: 2D numpy array representing the binary mask plane.
            frame_index: Index of the frame to set.
            channel: Index or name of the channel to set.
            z_index: Index of the Z slice to set.

        Raises:
            ValueError: If the mask plane shape does not match the image plane shape
                        or if the mask contains non-binary values.
        """
        expected_shape = (self.shape[self._axes.index("Y")],
                          self.shape[self._axes.index("X")])
        if mask.shape != expected_shape:
            raise ValueError(f"Mask plane shape {mask.shape} does not match image plane "
                            f"shape {expected_shape}.")
        
        if not np.all((mask == 0) | (mask == 1)):
            raise ValueError("Mask planes must be binary with values 0 and 1.")
        
        self._plane_selection(frame_index, channel, z_index)
        self._mask.set_plane((frame_index, self._resolve_channel(channel), z_index), mask)

    def clear_mask_plane(self, *, frame_index: int = 0, channel: int | str = 0, z_index: int = 0) -> None:
        """
        Clear a specific plane in the binary mask by setting it to all zeros.

        Args:
            frame_index: Index of the frame to clear.
            channel: Index or name of the channel to clear.
            z_index: Index of the Z slice to clear.
        """
        self._plane_selection(frame_index, channel, z_index)
        self._mask.clear_plane((frame_index, self._resolve_channel(channel), z_index))

    def clear_stack(self, *, channel: int | str = 0) -> None:
        """Clear one channel across T/Z in the session without writing an artifact."""
        for frame_index in range(self.frame_count):
            for z_index in range(self.plane_count):
                self.clear_mask_plane(
                    frame_index=frame_index, channel=channel, z_index=z_index)

    def completed_mask(self, interpolation_axis: str, *,
                       extrapolate_start: bool = True,
                       extrapolate_end: bool = True) -> NDArray[np.uint8]:
        """
        Complete the binary mask by filling in missing planes along the specified interpolation axis.

        Args:
            interpolation_axis: Axis along which to interpolate missing mask planes.
            extrapolate_start: Whether to extrapolate the mask at the start of the axis.
            extrapolate_end: Whether to extrapolate the mask at the end of the axis.

        Returns:
            A copy of the completed binary mask as a 3D numpy array.
        """
        return cast(NDArray[np.uint8], fill_missing_masks(self._mask.copy(), axes=self._axes,
                                                        interpolation_axis=interpolation_axis,
                                                        extrapolate_start=extrapolate_start,
                                                        extrapolate_end=extrapolate_end))

    def _channel_mask(self, channel_index: int) -> NDArray[np.uint8]:
        """
        Get the binary mask for a specific channel.

        Args:
            channel_index: Index of the channel to retrieve the mask for.

        Returns:
            A copy of the binary mask for the specified channel as a 3D numpy array.
        """
        return self._mask.copy(channel=channel_index)

    def close(self) -> None:
        self.preview_cache.close()
        self._mask.close()
        super().close()
