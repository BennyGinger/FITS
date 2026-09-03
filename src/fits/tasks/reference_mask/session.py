from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from fits.environment.constant import ARTI_REF, DIST_FITS
from fits.sessions.binary import BinaryMaskSession
from fits.tasks.reference_mask.artifact import (
    build_reference_path,
    load_reference_artifact,
    merge_reference_channels,
    saved_reference_channels,
    validate_reference_label,
)


class ReferenceMaskSession(BinaryMaskSession):
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
        self._reference_label: str | None = None
        self._loaded_channels: tuple[str, ...] = ()
        self._edit_history: dict[tuple[int, int, int], list[NDArray[np.uint8]]] = {}
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
            output_mask = self._complete_channel_mask(
                output_mask, output_axes, interpolation_axis,
                extrapolate_start, extrapolate_end)
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

    def interpolated_mask_plane(self, interpolation_axis: str, *,
                                frame_index: int = 0,
                                channel: int | str = 0,
                                z_index: int = 0,
                                extrapolate_start: bool = True,
                                extrapolate_end: bool = True,
                                ) -> NDArray[np.uint8]:
        """Return one plane from an interpolated copy of the drawing session."""
        completed = self.completed_mask(
            interpolation_axis, extrapolate_start=extrapolate_start,
            extrapolate_end=extrapolate_end)
        return self._select_plane(
            completed, frame_index=frame_index,
            channel=channel, z_index=z_index).copy()

    def apply_display_edit(self, mask: NDArray[np.generic], *,
                           comparison_mask: NDArray[np.generic],
                           frame_index: int = 0, channel: int | str = 0,
                           z_index: int = 0) -> None:
        """Commit only pixels changed relative to a possibly interpolated view."""
        current = self.mask_plane(frame_index, channel, z_index)
        visible = (np.asarray(mask) != 0).astype(np.uint8)
        comparison = (np.asarray(comparison_mask) != 0).astype(np.uint8)
        if visible.shape != current.shape or comparison.shape != current.shape:
            raise ValueError("Reference drawing and preview must match the image plane.")
        key = frame_index, self._resolve_channel(channel), z_index
        self._edit_history.setdefault(key, []).append(current.copy())
        del self._edit_history[key][:-50]
        changed = visible != comparison
        current[changed] = visible[changed]
        self.set_mask_plane(current, frame_index=frame_index,
                            channel=channel, z_index=z_index)

    def replace_display_mask(self, mask: NDArray[np.generic], *,
                             frame_index: int = 0, channel: int | str = 0,
                             z_index: int = 0) -> None:
        """Replace a plane while retaining the previous plane for Undo."""
        key = frame_index, self._resolve_channel(channel), z_index
        self._edit_history.setdefault(key, []).append(
            self.mask_plane(frame_index, channel, z_index))
        del self._edit_history[key][:-50]
        self.set_mask_plane(mask, frame_index=frame_index,
                            channel=channel, z_index=z_index)

    def undo_display_edit(self, *, frame_index: int = 0,
                          channel: int | str = 0,
                          z_index: int = 0) -> NDArray[np.uint8] | None:
        key = frame_index, self._resolve_channel(channel), z_index
        history = self._edit_history.get(key)
        if not history:
            return None
        restored = history.pop()
        self.set_mask_plane(restored, frame_index=frame_index,
                            channel=channel, z_index=z_index)
        return restored.copy()

    def clear_mask_plane(self, *, frame_index: int = 0,
                         channel: int | str = 0, z_index: int = 0) -> None:
        key = frame_index, self._resolve_channel(channel), z_index
        self._edit_history.setdefault(key, []).append(
            self.mask_plane(frame_index, channel, z_index))
        del self._edit_history[key][:-50]
        super().clear_mask_plane(
            frame_index=frame_index, channel=channel, z_index=z_index)

    @staticmethod
    def _complete_channel_mask(mask: NDArray[np.uint8], axes: str,
                               interpolation_axis: str,
                               extrapolate_start: bool,
                               extrapolate_end: bool) -> NDArray[np.uint8]:
        from mask_interpolation import fill_missing_masks
        return np.asarray(fill_missing_masks(
            mask, axes=axes, interpolation_axis=interpolation_axis,
            extrapolate_start=extrapolate_start,
            extrapolate_end=extrapolate_end), dtype=np.uint8)
