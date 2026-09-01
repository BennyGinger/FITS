from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from fits.environment.constant import FITS_ARRAY_NAME
from fits_io import FitsIO


class FitsImageSession:
    """
    Load and navigate one normalized FITS image artifact.

    This class owns the common image state required by interactive FITS
    sessions without defining tool-specific processing or lifecycle behavior.
    """

    def __init__(self, source_path: str | Path) -> None:
        self.source_path = Path(source_path).expanduser().resolve()
        if not self.source_path.is_file():
            raise FileNotFoundError(
                f"FITS image session source does not exist: {self.source_path}")
        if self.source_path.name != FITS_ARRAY_NAME:
            raise ValueError(
                "FITS image sessions only accept the normalized image artifact "
                f"named {FITS_ARRAY_NAME!r}; got {self.source_path.name!r}.")

        self._reader = FitsIO.from_path(self.source_path)
        loaded = self._reader.get_array()
        self._array = np.asarray(loaded.array)
        self._axes = loaded.axes
        self._channel_labels = tuple(self._reader.channel_labels)

        if len(self._axes) != self._array.ndim:
            raise ValueError(
                f"Image axes {self._axes!r} do not match shape {self._array.shape}.")
        if "Y" not in self._axes or "X" not in self._axes:
            raise ValueError(f"FITS image sessions require YX axes; got {self._axes!r}.")
        expected_channels = self._array.shape[self._axes.index("C")] if "C" in self._axes else 1
        if len(self._channel_labels) != expected_channels:
            raise ValueError(
                f"Image has {expected_channels} channels but "
                f"{len(self._channel_labels)} channel labels.")

    @property
    def axes(self) -> str:
        return self._axes

    @property
    def shape(self) -> tuple[int, ...]:
        return self._array.shape

    @property
    def channel_labels(self) -> tuple[str, ...]:
        return self._channel_labels

    @property
    def frame_count(self) -> int:
        return self._axis_size("T")

    @property
    def plane_count(self) -> int:
        return self._axis_size("Z")

    def display_frame(self,
                      frame_index: int = 0,
                      channel: int | str = 0,
                      z_index: int = 0,
                      ) -> NDArray[Any]:
        """Return one selected ``YX`` image plane as a view of the source array."""
        return self._select_plane(
            self._array, frame_index=frame_index, channel=channel, z_index=z_index)

    def _select_plane(self,
                      array: NDArray[Any],
                      *,
                      frame_index: int,
                      channel: int | str,
                      z_index: int,
                      ) -> NDArray[Any]:
        """Select one ``YX`` plane from an image-shaped array."""
        plane = array[self._plane_selection(frame_index, channel, z_index)]
        remaining_axes = "".join(
            axis for axis in self._axes if axis not in {"T", "C", "Z"})
        if remaining_axes != "YX":
            raise ValueError(
                f"A selected image plane must resolve to YX; got {remaining_axes!r}.")
        return plane

    def _plane_selection(self,
                         frame_index: int,
                         channel: int | str,
                         z_index: int,
                         ) -> tuple[int | slice, ...]:
        """Build an index selecting one time, channel, and Z position."""
        channel_index = self._resolve_channel(channel)
        self._validate_axis_index("T", frame_index, "Frame")
        self._validate_axis_index("Z", z_index, "Z")

        selection: list[int | slice] = [slice(None)] * self._array.ndim
        if "T" in self._axes:
            selection[self._axes.index("T")] = frame_index
        if "C" in self._axes:
            selection[self._axes.index("C")] = channel_index
        if "Z" in self._axes:
            selection[self._axes.index("Z")] = z_index
        return tuple(selection)

    def _resolve_channel(self, channel: int | str) -> int:
        """Resolve a channel against the channels present in this image artifact."""
        if isinstance(channel, int):
            index = channel
        else:
            try:
                index = self._channel_labels.index(channel)
            except ValueError as error:
                raise ValueError(
                    f"Unknown channel {channel!r}; available channels: "
                    f"{self._channel_labels}.") from error
        if index < 0 or index >= len(self._channel_labels):
            raise IndexError(
                f"Channel index {index} is outside 0..{len(self._channel_labels) - 1}.")
        if "C" not in self._axes and index != 0:
            raise IndexError("An image without a C axis only has channel index 0.")
        return index

    def _validate_axis_index(self, axis: str, index: int, label: str) -> None:
        """Validate one optional navigation-axis index."""
        if axis not in self._axes:
            if index != 0:
                raise IndexError(f"An image without a {axis} axis only has index 0.")
            return
        axis_size = self._array.shape[self._axes.index(axis)]
        if index < 0 or index >= axis_size:
            raise IndexError(f"{label} index {index} is outside 0..{axis_size - 1}.")

    def _axis_size(self, axis: str) -> int:
        """Return an optional navigation axis size, defaulting to one."""
        if axis not in self._axes:
            return 1
        return self._array.shape[self._axes.index(axis)]
