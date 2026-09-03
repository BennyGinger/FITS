from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from fits.environment.constant import ARTI_ROI, DIST_FITS
from fits.sessions.binary import BinaryMaskSession
from fits.tasks.reference_mask.artifact import validate_reference_label
from fits.tasks.roi_mask.artifact import (
    ROI_MASK_ENCODING,
    ROI_MASK_VALUE_TABLE,
    build_roi_path,
    load_roi_artifact,
    merge_roi_channels,
    saved_roi_channels,
)


class RoiSession(BinaryMaskSession):
    """Create ordered ROI states while preserving threshold and manual decisions.

    States 0 to 2 are excluded from analysis and states 3 to 5 are included.
    Each value also retains the threshold result and any manual override.
    """

    THRESHOLD_EXCLUDED = np.uint8(0)
    MANUALLY_EXCLUDED = np.uint8(1)
    THRESHOLD_INCLUDED_MANUALLY_EXCLUDED = np.uint8(2)
    MANUALLY_INCLUDED = np.uint8(3)
    THRESHOLD_INCLUDED = np.uint8(4)
    THRESHOLD_INCLUDED_MANUALLY_INCLUDED = np.uint8(5)

    def __init__(self, source_path: str | Path, *,
                 roi_path: str | Path | None = None) -> None:
        super().__init__(source_path)
        self._roi_label: str | None = None
        self._loaded_channels: tuple[str, ...] = ()
        self._threshold_ranges: dict[tuple[int, int, int], tuple[float, float]] = {}
        self._edit_history: dict[tuple[int, int, int], list[NDArray[np.uint8]]] = {}
        if roi_path is not None:
            self._mask, self._roi_label, self._loaded_channels = load_roi_artifact(
                roi_path, source_path=self.source_path,
                source_axes=self._axes, source_shape=self._array.shape,
                source_channels=self._channel_labels)

    def display_mask_plane(self, frame_index: int = 0,
                           channel: int | str = 0,
                           z_index: int = 0) -> NDArray[np.uint8]:
        """Return the final binary ROI after applying manual threshold overrides."""
        return self._included(self.mask_plane(frame_index, channel, z_index))

    def apply_display_edit(self, mask: NDArray[np.generic], *,
                           frame_index: int = 0, channel: int | str = 0,
                           z_index: int = 0,
                           comparison_mask: NDArray[np.generic] | None = None,
                           edited_pixels: NDArray[np.generic] | None = None,
                           operation: str | None = None) -> None:
        """Translate an edited binary canvas into persistent manual ROI states."""
        current = self.mask_plane(frame_index, channel, z_index)
        visible = np.asarray(mask)
        if visible.shape != current.shape:
            raise ValueError(
                f"ROI drawing shape {visible.shape} does not match image plane "
                f"shape {current.shape}.")
        if not np.all((visible == 0) | (visible == 1)):
            raise ValueError("The editable ROI canvas must contain only 0 and 1.")
        key = self._plane_key(frame_index, channel, z_index)
        self._edit_history.setdefault(key, []).append(current.copy())
        del self._edit_history[key][:-50]
        updated = current.copy()
        if edited_pixels is not None:
            selected = np.asarray(edited_pixels, dtype=bool)
            if selected.shape != current.shape:
                raise ValueError("ROI edited-pixel selection does not match the image plane.")
            if operation == "add":
                updated[selected] = np.where(
                    self._threshold_included(updated[selected]),
                    self.THRESHOLD_INCLUDED_MANUALLY_INCLUDED,
                    self.MANUALLY_INCLUDED)
            elif operation == "erase":
                updated[selected] = np.where(
                    self._threshold_included(updated[selected]),
                    self.THRESHOLD_INCLUDED_MANUALLY_EXCLUDED,
                    self.MANUALLY_EXCLUDED)
            else:
                raise ValueError("ROI drawing operation must be 'add' or 'erase'.")
            self._set_roi_plane(updated, frame_index=frame_index,
                                channel=channel, z_index=z_index)
            return
        was_visible = (self._included(current).astype(bool)
                       if comparison_mask is None
                       else np.asarray(comparison_mask) != 0)
        if was_visible.shape != current.shape:
            raise ValueError("ROI comparison mask shape does not match the image plane.")
        additions = (visible != 0) & ~was_visible
        exclusions = (visible == 0) & was_visible
        updated[additions] = np.where(
            self._threshold_included(updated[additions]),
            self.THRESHOLD_INCLUDED_MANUALLY_INCLUDED,
            self.MANUALLY_INCLUDED)
        updated[exclusions] = np.where(
            self._threshold_included(updated[exclusions]),
            self.THRESHOLD_INCLUDED_MANUALLY_EXCLUDED,
            self.MANUALLY_EXCLUDED)
        self._set_roi_plane(updated, frame_index=frame_index,
                            channel=channel, z_index=z_index)

    def undo_display_edit(self, *, frame_index: int = 0,
                          channel: int | str = 0,
                          z_index: int = 0) -> NDArray[np.uint8] | None:
        """Restore the ordered-state plane from before the latest drawing gesture."""
        key = self._plane_key(frame_index, channel, z_index)
        history = self._edit_history.get(key)
        if not history:
            return None
        self._set_roi_plane(history.pop(), frame_index=frame_index,
                            channel=channel, z_index=z_index)
        return self.display_mask_plane(frame_index, channel, z_index)

    def fill_holes(self, *, frame_index: int = 0,
                   channel: int | str = 0,
                   z_index: int = 0) -> bool:
        """Fill enclosed holes on one plane as manual inclusions."""
        from scipy.ndimage import binary_fill_holes

        current = self.mask_plane(frame_index, channel, z_index)
        visible = self._included(current).astype(bool)
        additions = binary_fill_holes(visible) & ~visible
        if not np.any(additions):
            return False
        self._remember_edit(current, frame_index, channel, z_index)
        current[additions] = np.where(
            self._threshold_included(current[additions]),
            self.THRESHOLD_INCLUDED_MANUALLY_INCLUDED,
            self.MANUALLY_INCLUDED)
        self._set_roi_plane(current, frame_index=frame_index,
                            channel=channel, z_index=z_index)
        return True

    def remove_small_objects(self, minimum_size: int, *,
                             frame_index: int = 0,
                             channel: int | str = 0,
                             z_index: int = 0) -> bool:
        """Manually exclude 8-connected objects smaller than ``minimum_size``."""
        from scipy.ndimage import label

        if minimum_size < 1:
            raise ValueError("Minimum ROI object size must be at least 1 pixel.")
        current = self.mask_plane(frame_index, channel, z_index)
        components, count = label(
            self._included(current).astype(bool),
            structure=np.ones((3, 3), dtype=np.uint8))
        if count == 0:
            return False
        sizes = np.bincount(components.ravel())
        small_labels = np.flatnonzero((sizes < minimum_size) & (np.arange(sizes.size) != 0))
        exclusions = np.isin(components, small_labels)
        if not np.any(exclusions):
            return False
        self._remember_edit(current, frame_index, channel, z_index)
        current[exclusions] = np.where(
            self._threshold_included(current[exclusions]),
            self.THRESHOLD_INCLUDED_MANUALLY_EXCLUDED,
            self.MANUALLY_EXCLUDED)
        self._set_roi_plane(current, frame_index=frame_index,
                            channel=channel, z_index=z_index)
        return True

    def _remember_edit(self, current: NDArray[np.uint8], frame_index: int,
                       channel: int | str, z_index: int) -> None:
        key = self._plane_key(frame_index, channel, z_index)
        self._edit_history.setdefault(key, []).append(current.copy())
        del self._edit_history[key][:-50]

    def interpolated_display_mask_plane(
            self, interpolation_axis: str, *, frame_index: int = 0,
            channel: int | str = 0, z_index: int = 0,
            extrapolate_start: bool = True,
            extrapolate_end: bool = True) -> NDArray[np.uint8]:
        """Return a binary display plane from interpolated manual corrections."""
        completed = self._complete_manual_corrections(
            self._mask, self._axes, interpolation_axis,
            extrapolate_start, extrapolate_end)
        plane = self._select_plane(
            completed, frame_index=frame_index,
            channel=channel, z_index=z_index)
        return self._included(plane)

    @property
    def roi_label(self) -> str | None:
        return self._roi_label

    @property
    def loaded_channels(self) -> tuple[str, ...]:
        return self._loaded_channels

    def set_mask_plane(self, mask: NDArray[np.generic], *,
                       frame_index: int = 0, channel: int | str = 0,
                       z_index: int = 0) -> None:
        """Store an ordered ROI-state plane with threshold/manual provenance."""
        self._set_roi_plane(mask, frame_index=frame_index,
                            channel=channel, z_index=z_index)

    def threshold_plane(self, minimum: float, maximum: float, *,
                        frame_index: int = 0, channel: int | str = 0,
                        z_index: int = 0) -> NDArray[np.uint8]:
        image = self.display_frame(frame_index, channel, z_index)
        selected = (image > minimum) & (image <= maximum)
        current = self.mask_plane(frame_index, channel, z_index)
        manually_added = self._manually_added(current)
        manually_excluded = self._manually_excluded(current)
        current[:] = np.where(
            selected, self.THRESHOLD_INCLUDED, self.THRESHOLD_EXCLUDED)
        current[manually_added & ~selected] = self.MANUALLY_INCLUDED
        current[manually_added & selected] = (
            self.THRESHOLD_INCLUDED_MANUALLY_INCLUDED)
        current[manually_excluded & ~selected] = self.MANUALLY_EXCLUDED
        current[manually_excluded & selected] = (
            self.THRESHOLD_INCLUDED_MANUALLY_EXCLUDED)
        self._set_roi_plane(current, frame_index=frame_index,
                            channel=channel, z_index=z_index)
        self._threshold_ranges[
            self._plane_key(frame_index, channel, z_index)] = (
                float(minimum), float(maximum))
        return current.copy()

    def threshold_range(self, *, frame_index: int = 0,
                        channel: int | str = 0,
                        z_index: int = 0) -> tuple[float, float] | None:
        """Return the threshold range last applied to one plane, if available."""
        return self._threshold_ranges.get(
            self._plane_key(frame_index, channel, z_index))

    def otsu_threshold(self, *, frame_index: int = 0,
                       channel: int | str = 0, z_index: int = 0) -> float:
        """Return an Otsu threshold calculated from finite pixels of one plane."""
        values = np.asarray(self.display_frame(frame_index, channel, z_index), dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            raise ValueError("Cannot threshold an image without finite pixels.")
        if np.min(values) == np.max(values):
            raise ValueError("Otsu thresholding requires more than one intensity value.")
        hist, edges = np.histogram(values, bins=min(256, max(2, int(np.sqrt(values.size)))))
        centres = (edges[:-1] + edges[1:]) / 2
        weight_left = np.cumsum(hist)
        weight_right = np.cumsum(hist[::-1])[::-1]
        mean_left = np.cumsum(hist * centres) / np.maximum(weight_left, 1)
        mean_right = (np.cumsum((hist * centres)[::-1])
                      / np.maximum(weight_right[::-1], 1))[::-1]
        variance = (weight_left[:-1] * weight_right[1:]
                    * (mean_left[:-1] - mean_right[1:]) ** 2)
        return float(centres[int(np.argmax(variance))])

    def apply_otsu(self, *, frame_index: int = 0, channel: int | str = 0,
                   z_index: int = 0) -> float | None:
        """Apply Otsu to one plane, clearing planes without intensity contrast."""
        try:
            threshold = self.otsu_threshold(
                frame_index=frame_index, channel=channel, z_index=z_index)
        except ValueError:
            self._clear_threshold_plane(
                frame_index=frame_index, channel=channel, z_index=z_index)
            return None
        image = self.display_frame(frame_index, channel, z_index)
        self.threshold_plane(
            threshold, float(np.nanmax(image)), frame_index=frame_index,
            channel=channel, z_index=z_index)
        return threshold

    def _clear_threshold_plane(self, *, frame_index: int = 0,
                               channel: int | str = 0,
                               z_index: int = 0) -> None:
        selection = self._plane_selection(frame_index, channel, z_index)
        current = self._mask[selection]
        current[self._manually_added(current)] = self.MANUALLY_INCLUDED
        current[self._manually_excluded(current)] = self.MANUALLY_EXCLUDED
        current[current == self.THRESHOLD_INCLUDED] = self.THRESHOLD_EXCLUDED
        self._threshold_ranges.pop(
            self._plane_key(frame_index, channel, z_index), None)

    def threshold_stack(self, *, channel: int | str = 0) -> int:
        """Apply independent Otsu thresholds and return the empty-plane count."""
        empty_planes = 0
        for frame_index in range(self.frame_count):
            for z_index in range(self.plane_count):
                if self.apply_otsu(
                        frame_index=frame_index, channel=channel,
                        z_index=z_index) is None:
                    empty_planes += 1
        return empty_planes

    def clear_stack(self, *, channel: int | str = 0) -> None:
        """Clear every T/Z plane for one source channel."""
        for frame_index in range(self.frame_count):
            for z_index in range(self.plane_count):
                self.clear_mask_plane(
                    frame_index=frame_index, channel=channel, z_index=z_index)

    def threshold_stack_range(self, minimum: float, maximum: float, *,
                              channel: int | str = 0) -> None:
        """Apply one explicit intensity range to every T/Z plane of a channel."""
        if minimum > maximum:
            raise ValueError("ROI threshold minimum cannot exceed its maximum.")
        for frame_index in range(self.frame_count):
            for z_index in range(self.plane_count):
                self.threshold_plane(
                    minimum, maximum, frame_index=frame_index,
                    channel=channel, z_index=z_index)

    def clear_mask_plane(self, *, frame_index: int = 0,
                         channel: int | str = 0, z_index: int = 0) -> None:
        key = self._plane_key(frame_index, channel, z_index)
        self._mask[self._plane_selection(frame_index, channel, z_index)] = (
            0)
        self._threshold_ranges.pop(key, None)
        self._edit_history.pop(key, None)

    def _set_roi_plane(self, mask: NDArray[np.generic], *,
                       frame_index: int = 0, channel: int | str = 0,
                       z_index: int = 0) -> None:
        array = np.asarray(mask)
        expected = self.mask_plane(frame_index, channel, z_index).shape
        if array.shape != expected:
            raise ValueError(f"ROI plane shape {array.shape} does not match {expected}.")
        if not np.all(np.isin(array, (0, 1, 2, 3, 4, 5))):
            raise ValueError(
                "ROI planes must contain ordered threshold/manual states 0 to 5.")
        self._mask[self._plane_selection(frame_index, channel, z_index)] = (
            array.astype(np.uint8, copy=False))

    def _plane_key(self, frame_index: int, channel: int | str,
                   z_index: int) -> tuple[int, int, int]:
        return frame_index, self._resolve_channel(channel), z_index

    def save(self, label: str, *, channel: int | str = 0,
             interpolation_axis: str | None = None,
             extrapolate_start: bool = True,
             extrapolate_end: bool = True,
             overwrite: bool = False, compression: str | None = "zlib") -> Path:
        normalized = validate_reference_label(label)
        channel_index = self._resolve_channel(channel)
        channel_label = self._channel_labels[channel_index]
        output_path = build_roi_path(self.source_path, normalized)
        output_mask = self._channel_mask(channel_index)
        if not np.any(self._included(output_mask)):
            raise ValueError(f"Cannot save ROI channel {channel_label!r} without selected pixels.")
        output_axes = self._axes.replace("C", "")
        if interpolation_axis is not None:
            output_mask = self._complete_manual_corrections(
                output_mask, output_axes, interpolation_axis,
                extrapolate_start, extrapolate_end)
        output_mask, output_labels = merge_roi_channels(
            output_path, output_mask, channel_axes=output_axes,
            source_axes=self._axes, channel_label=channel_label,
            overwrite=overwrite)
        return self._reader.save_array(
            output_mask.astype(np.uint16, copy=False),
            channel_labels=self._channel_labels,
            export_channels=output_labels, artifact_kind=ARTI_ROI,
            created_by=DIST_FITS, output_path=output_path,
            custom_metadata={
                "roi_mask_encoding": ROI_MASK_ENCODING,
                "roi_mask_value_table": ROI_MASK_VALUE_TABLE,
            },
            compression=compression)

    def saved_channels(self, label: str) -> tuple[str, ...]:
        return saved_roi_channels(build_roi_path(
            self.source_path, validate_reference_label(label)))

    @classmethod
    def _complete_manual_corrections(cls, mask: NDArray[np.uint8], axes: str,
                                     interpolation_axis: str,
                                     extrapolate_start: bool,
                                     extrapolate_end: bool) -> NDArray[np.uint8]:
        """Interpolate manual states while retaining each plane's own threshold."""
        from mask_interpolation import fill_missing_masks

        def complete(correction: NDArray[np.bool_]) -> NDArray[np.bool_]:
            correction = correction.astype(np.uint8)
            if not np.any(correction):
                return correction.astype(bool)
            return np.asarray(fill_missing_masks(
                correction, axes=axes, interpolation_axis=interpolation_axis,
                extrapolate_start=extrapolate_start,
                extrapolate_end=extrapolate_end), dtype=bool)

        manual_additions = complete(cls._manually_added(mask))
        manual_exclusions = complete(cls._manually_excluded(mask))
        threshold = cls._threshold_included(mask)
        completed = np.where(
            threshold, cls.THRESHOLD_INCLUDED,
            cls.THRESHOLD_EXCLUDED).astype(np.uint8)
        completed[manual_additions & ~threshold] = cls.MANUALLY_INCLUDED
        completed[manual_additions & threshold] = (
            cls.THRESHOLD_INCLUDED_MANUALLY_INCLUDED)
        completed[manual_exclusions & ~threshold] = cls.MANUALLY_EXCLUDED
        completed[manual_exclusions & threshold] = (
            cls.THRESHOLD_INCLUDED_MANUALLY_EXCLUDED)
        return completed

    @classmethod
    def _included(cls, mask: NDArray[np.generic]) -> NDArray[np.uint8]:
        return (np.asarray(mask) >= cls.MANUALLY_INCLUDED).astype(np.uint8)

    @staticmethod
    def _threshold_included(mask: NDArray[np.generic]) -> NDArray[np.bool_]:
        return np.isin(mask, (2, 4, 5))

    @staticmethod
    def _manually_added(mask: NDArray[np.generic]) -> NDArray[np.bool_]:
        return np.isin(mask, (3, 5))

    @staticmethod
    def _manually_excluded(mask: NDArray[np.generic]) -> NDArray[np.bool_]:
        return np.isin(mask, (1, 2))
