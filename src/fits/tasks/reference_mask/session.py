from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
from mask_interpolation import fill_missing_masks
from numpy.typing import NDArray

from fits.environment.constant import ARTI_REF, DIST_FITS
from fits.sessions.image import FitsImageSession
from fits.tasks.reference_mask.artifact import (
    build_reference_path,
    load_reference_artifact,
    merge_reference_channels,
    saved_reference_channels,
    validate_reference_label,
)


class ReferenceMaskSession(FitsImageSession):
    """
    Manage user-drawn reference masks for one normalized FITS image.

    The drawing UI operates on individual ``YX`` planes through
    :meth:`set_mask_plane`, while the session retains a binary mask array with
    the same shape and axes as the source image. Interpolation always returns a
    copy, preserving the original user-drawn anchors.
    """

    def __init__(self,
                 source_path: str | Path,
                 *,
                 reference_path: str | Path | None = None,
                 ) -> None:
        super().__init__(source_path)
        self._mask = np.zeros(self._array.shape, dtype=np.uint8)
        self._reference_label: str | None = None
        self._loaded_channels: tuple[str, ...] = ()
        if reference_path is not None:
            self._mask, self._reference_label, self._loaded_channels = (
                load_reference_artifact(
                    reference_path,
                    source_path=self.source_path,
                    source_axes=self._axes,
                    source_shape=self._array.shape,
                    source_channels=self._channel_labels,))

    @property
    def reference_label(self) -> str | None:
        """Return the label parsed from the loaded reference filename."""
        return self._reference_label

    @property
    def loaded_channels(self) -> tuple[str, ...]:
        """Return source channels imported from the loaded reference artifact."""
        return self._loaded_channels

    @property
    def mask_array(self) -> NDArray[np.uint8]:
        """Return a copy of the user-drawn mask anchors."""
        return self._mask.copy()

    def mask_plane(self,
                   frame_index: int = 0,
                   channel: int | str = 0,
                   z_index: int = 0,
                   ) -> NDArray[np.uint8]:
        """Return a copy of the selected user-drawn ``YX`` mask plane."""
        return self._select_plane(
            self._mask, frame_index=frame_index,
            channel=channel, z_index=z_index).copy()

    def set_mask_plane(self,
                       mask: NDArray[np.generic],
                       *,
                       frame_index: int = 0,
                       channel: int | str = 0,
                       z_index: int = 0,
                       ) -> None:
        """
        Replace one selected plane with a binary mask supplied by the drawing UI.
        """
        expected_shape = (
            self._array.shape[self._axes.index("Y")],
            self._array.shape[self._axes.index("X")],)
        if mask.shape != expected_shape:
            raise ValueError(
                f"Mask plane shape {mask.shape} does not match image plane "
                f"shape {expected_shape}.")
        if not np.all((mask == 0) | (mask == 1)):
            raise ValueError("Mask planes must be binary with values 0 and 1.")

        selection = self._plane_selection(frame_index, channel, z_index)
        self._mask[selection] = mask.astype(np.uint8, copy=False)

    def clear_mask_plane(self,
                         *,
                         frame_index: int = 0,
                         channel: int | str = 0,
                         z_index: int = 0,
                         ) -> None:
        """Clear one selected user-drawn mask plane."""
        self._mask[self._plane_selection(frame_index, channel, z_index)] = 0

    def completed_mask(self,
                       interpolation_axis: str,
                       *,
                       extrapolate_start: bool = True,
                       extrapolate_end: bool = True,
                       ) -> NDArray[np.uint8]:
        """Return a completed copy of the mask without changing drawn anchors."""
        return cast(
            NDArray[np.uint8],
            fill_missing_masks(
                self._mask,
                axes=self._axes,
                interpolation_axis=interpolation_axis,
                extrapolate_start=extrapolate_start,
                extrapolate_end=extrapolate_end,))

    def save(self,
             label: str,
             *,
             channel: int | str = 0,
             interpolation_axis: str | None = None,
             extrapolate_start: bool = True,
             extrapolate_end: bool = True,
             overwrite: bool = False,
             compression: str | None = "zlib",
             ) -> Path:
        """
        Save the selected channel as ``fits_ref_<label>.tif``.

        A one-channel artifact has no ``C`` axis. Saving another source channel
        under the same label appends it to the existing artifact; saving a
        channel already present requires ``overwrite=True``. Providing
        ``interpolation_axis`` fills missing masks in the saved copy. The
        session's user-drawn anchors remain unchanged.
        """
        normalized_label = validate_reference_label(label)
        channel_index = self._resolve_channel(channel)
        channel_label = self._channel_labels[channel_index]
        output_path = build_reference_path(self.source_path, normalized_label)
        output_mask = self._channel_mask(channel_index)
        output_axes = self._axes.replace("C", "")
        if not np.any(output_mask):
            raise ValueError(
                f"Cannot save reference channel {channel_label!r} without any drawn planes.")
        if interpolation_axis is not None:
            output_mask = cast(
                NDArray[np.uint8],
                fill_missing_masks(
                    output_mask,
                    axes=output_axes,
                    interpolation_axis=interpolation_axis,
                    extrapolate_start=extrapolate_start,
                    extrapolate_end=extrapolate_end,))
        output_mask, output_labels = merge_reference_channels(
            output_path,
            output_mask,
            channel_axes=output_axes,
            source_axes=self._axes,
            channel_label=channel_label,
            overwrite=overwrite,)

        return self._reader.save_array(
            output_mask.astype(np.uint16, copy=False),
            channel_labels=self._channel_labels,
            export_channels=output_labels,
            artifact_kind=ARTI_REF,
            created_by=DIST_FITS,
            output_path=output_path,
            compression=compression,)

    def saved_channels(self, label: str) -> tuple[str, ...]:
        """Return channel labels already stored in one reference artifact."""
        output_path = build_reference_path(
            self.source_path, validate_reference_label(label))
        return saved_reference_channels(output_path)

    def _channel_mask(self, channel_index: int) -> NDArray[np.uint8]:
        if "C" not in self._axes:
            return self.mask_array
        return np.take(self._mask, channel_index, axis=self._axes.index("C")).copy()
