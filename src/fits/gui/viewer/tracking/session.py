"""Artifact loading and navigation for the tracking viewer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from fits_io import FitsIO

from fits.environment.constant import (
    DIST_FITS,
    FITS_ARRAY_NAME,
    FITS_MASK_TRACK,
    FITS_MASK_TRACK_EDITED,
    FITS_MASK_TRACK_EDITED_FILTERED,
    StepName,
)
from fits.gui.viewer.tracking.rendering import render_selected_tracking_display
from fits.gui.viewer.tracking.trajectories import calculate_track_centroids
from fits.interaction import FitsImageSession
from fits.tasks.segmentation.local_seg import (
    AddEditBackend,
    AddEditProposal,
    DEFAULT_MICROSAM_BACKEND,
    SplitPredictor,
    fill_enclosed_mask,
)
from fits.workflows.metadata._values import distribution_version, utc_now
from fits.workflows.metadata import FitsMeta

# Keep corrective clicks local to the current displayed mask.
MICROSAM_POSITIVE_REFINEMENT_RADIUS = 0.30
MICROSAM_NEGATIVE_REFINEMENT_RADIUS = 0.10


def _register_mask_translation(
        previous_image: NDArray, current_image: NDArray,
        previous_mask: NDArray, expected_diameter: float,
        ) -> tuple[NDArray[np.bool_], tuple[float, float], float]:
    """Translate a mask with crop-local OpenCV phase correlation and ECC."""
    import cv2

    mask = np.asarray(previous_mask, dtype=bool)
    coordinates = np.column_stack(np.nonzero(mask))
    if coordinates.size == 0:
        return mask.copy(), (0.0, 0.0), 0.0

    shape = mask.shape
    margin = max(12, int(round(expected_diameter * 1.5)))
    y0 = max(0, int(np.min(coordinates[:, 0])) - margin)
    y1 = min(shape[0], int(np.max(coordinates[:, 0])) + margin + 1)
    x0 = max(0, int(np.min(coordinates[:, 1])) - margin)
    x1 = min(shape[1], int(np.max(coordinates[:, 1])) + margin + 1)

    def normalized_crop(image: NDArray) -> NDArray[np.float32]:
        crop = np.nan_to_num(
            np.asarray(image[y0:y1, x0:x1], dtype=np.float32), copy=True)
        crop -= float(np.min(crop))
        scale = float(np.max(crop))
        if scale > 0:
            crop /= scale
        return np.asarray(cv2.GaussianBlur(crop, (5, 5), 0), dtype=np.float32)

    reference = normalized_crop(previous_image)
    moving = normalized_crop(current_image)
    if not np.any(reference) or not np.any(moving):
        return mask.copy(), (0.0, 0.0), 0.0

    (phase_x, phase_y), phase_response = cv2.phaseCorrelate(reference, moving)
    warp = np.asarray(
        [[1.0, 0.0, phase_x], [0.0, 1.0, phase_y]], dtype=np.float32)
    try:
        ecc_score, warp = cv2.findTransformECC(
            reference, moving, warp, cv2.MOTION_TRANSLATION,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 1e-4),
            None, 3)
        confidence = float(ecc_score)
    except cv2.error:
        confidence = float(phase_response)

    shift_x = float(warp[0, 2])
    shift_y = float(warp[1, 2])
    maximum_shift = max(8.0, float(expected_diameter) * 3.0)
    if (not np.isfinite(confidence) or confidence < 0.1
            or np.hypot(shift_y, shift_x) > maximum_shift):
        return mask.copy(), (0.0, 0.0), 0.0

    translated = cv2.warpAffine(
        mask.astype(np.uint8),
        np.asarray([[1.0, 0.0, shift_x], [0.0, 1.0, shift_y]], dtype=np.float32),
        (shape[1], shape[0]), flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return np.asarray(translated, dtype=bool), (shift_y, shift_x), confidence



@dataclass(frozen=True)
class _TrackingUndo:
    channel: int
    z_index: int
    frames: tuple[int, ...]
    planes: tuple[NDArray[Any], ...]
    has_edits: bool
    operations_used: frozenset[str]
    edited_mask_channels: frozenset[int]
    prediction_channels: tuple[dict[str, str], ...]


class TrackingViewerSession:
    """

    Load and navigate a tracked-label artifact and optional sibling image.

    """

    _add_edit_backend: AddEditBackend = DEFAULT_MICROSAM_BACKEND

    def __init__(self, tracking_path: str | Path,
                 image_path: str | Path | None = None, *,
                 add_edit_backend: AddEditBackend = DEFAULT_MICROSAM_BACKEND) -> None:
        self._add_edit_backend = add_edit_backend
        self.source_path = Path(tracking_path).expanduser().resolve()
        tracking_names = {
            FITS_MASK_TRACK,
            FITS_MASK_TRACK_EDITED,
            FITS_MASK_TRACK_EDITED_FILTERED,
        }
        if not self.source_path.is_file() or self.source_path.name not in {
                *tracking_names, FITS_ARRAY_NAME}:
            raise ValueError(
                f"Select a FITS tracking mask or {FITS_ARRAY_NAME!r}.")
        if self.source_path.name == FITS_ARRAY_NAME:
            self.image_session = FitsImageSession(self.source_path)
            self._reader = self.image_session._reader
            self._tracks = np.zeros(self.image_session.shape, dtype=np.uint32)
            self._axes = self.image_session.axes
            self._channel_labels = self.image_session.channel_labels
            self._started_from_image = True
        else:
            self._reader = FitsIO.from_path(self.source_path)
            result = self._reader.get_array()
            self._tracks = np.asarray(result.array)
            self._axes = result.axes
            self._channel_labels = tuple(self._reader.channel_labels)
            associated_image = (Path(image_path).expanduser().resolve()
                                if image_path is not None
                                else self.source_path.with_name(FITS_ARRAY_NAME))
            self.image_session = (FitsImageSession(associated_image)
                                  if associated_image.is_file() else None)
            self._started_from_image = False
        self._centroid_cache: dict[tuple[int, int], dict[int, NDArray[np.float64]]] = {}
        self._split_predictor = SplitPredictor()
        self._has_edits = False
        self._operations_used: set[str] = set()
        self._edited_mask_channels: set[int] = set()
        self._prediction_channels: list[dict[str, str]] = []
        self._undo_history: list[_TrackingUndo] = []
        self._original_add_edit_masks: dict[
            tuple[int, int, int, int], NDArray[np.bool_]] = {}
        if len(self._axes) != self._tracks.ndim or not {"Y", "X"}.issubset(self._axes):
            raise ValueError(f"Tracking axes {self._axes!r} do not match a YX label movie "
                             f"with shape {self._tracks.shape}.")

        channel_count = self._axis_size("C")
        if not self._channel_labels:
            self._channel_labels = tuple(f"Channel {index + 1}" for index in range(channel_count))

        if len(self._channel_labels) != channel_count:
            raise ValueError(f"Tracking has {channel_count} channels but "
                            f"{len(self._channel_labels)} channel labels.")

    @property
    def started_from_image(self) -> bool:
        """Return whether this is a new empty tracking session."""
        return self._started_from_image

    @property
    def axes(self) -> str:
        return self._axes

    @property
    def shape(self) -> tuple[int, ...]:
        return self._tracks.shape

    @property
    def channel_labels(self) -> tuple[str, ...]:
        """

        Return channels available for optional raw-image display.

        """
        if self.image_session is not None:
            return self.image_session.channel_labels
        return ("No raw image",)

    @property
    def track_channel_labels(self) -> tuple[str, ...]:
        return self._channel_labels

    @property
    def frame_count(self) -> int:
        return self._axis_size("T")

    @property
    def plane_count(self) -> int:
        return self._axis_size("Z")

    @property
    def has_edits(self) -> bool:
        """Return whether the in-memory tracking labels have been modified."""
        return self._has_edits

    def display_frame(self, frame_index: int = 0, channel: int | str = 0, z_index: int = 0,) -> NDArray[Any]:
        """

        Return a raw-image plane or a blank plane shaped like the labels.

        """
        if self.image_session is None:
            labels = self.tracked_frame(frame_index, 0, z_index)
            return np.zeros(labels.shape, dtype=np.uint8)
        return self.image_session.display_frame(frame_index, channel, z_index)

    def tracked_frame(self, frame_index: int = 0, channel: int | str = 0, z_index: int = 0,) -> NDArray[Any]:
        """

        Return one selected ``YX`` plane from the tracking artifact.

        """
        selection: list[int | slice] = [slice(None)] * self._tracks.ndim
        for axis, value in (("T", frame_index),
                            ("C", self._resolve_channel(channel)),
                            ("Z", z_index),):
            if axis in self._axes:
                if value < 0 or value >= self._axis_size(axis):
                    raise IndexError(f"{axis} index {value} is outside the tracking artifact.")
                selection[self._axes.index(axis)] = value
            elif value != 0:
                raise IndexError(f"Tracking artifact has no {axis} axis.")
        plane = self._tracks[tuple(selection)]
        remaining = "".join(axis for axis in self._axes if axis not in {"T", "C", "Z"})
        if remaining != "YX":
            raise ValueError(f"A tracking plane must resolve to YX; got {remaining!r}.")
        return plane

    def track_centroids(self, channel: int | str = 0, z_index: int = 0,) -> dict[int, NDArray[np.float64]]:
        """

        Return cached centroid observations for every nonzero track.

        """
        channel_index = self._resolve_channel(channel)
        cache_key = (channel_index, z_index)
        cached = self._centroid_cache.get(cache_key)
        if cached is None:
            cached = calculate_track_centroids(self.tracked_frame,
                                                frame_count=self.frame_count,
                                                channel_index=channel_index,
                                                z_index=z_index,)
            self._centroid_cache[cache_key] = cached
        return cached

    def track_ids_matching(self,
                           channel: int | str,
                           z_index: int,
                           operator: str,
                           value: int,
                           maximum: int | None = None,
                           ) -> frozenset[int]:
        """Return track IDs whose number of observed frames matches a condition."""
        lengths = {
            track_id: len(points)
            for track_id, points in self.track_centroids(channel, z_index).items()
        }
        comparisons = {
            "lt": lambda length: length < value,
            "le": lambda length: length <= value,
            "eq": lambda length: length == value,
            "ne": lambda length: length != value,
            "ge": lambda length: length >= value,
            "gt": lambda length: length > value,
            "between": lambda length: maximum is not None and value <= length <= maximum,
        }
        try:
            comparison = comparisons[operator]
        except KeyError as error:
            raise ValueError(f"Unknown track-length comparison: {operator!r}.") from error
        if operator == "between" and (maximum is None or maximum < value):
            raise ValueError("The maximum track length must be at least the minimum.")
        return frozenset(track_id for track_id, length in lengths.items()
                         if comparison(length))

    def filtered_tracked_frame(self,
                               frame_index: int,
                               channel: int | str,
                               z_index: int,
                               track_ids: frozenset[int] | None,
                               ) -> NDArray[Any]:
        """Return one label plane with rejected track IDs replaced by zero."""
        labels = self.tracked_frame(frame_index, channel, z_index)
        if track_ids is None:
            return labels
        return np.where(np.isin(labels, tuple(track_ids)), labels, 0)

    def merge_tracks(self, track_ids: tuple[int, int], frame_index: int,
                     channel: int | str, z_index: int) -> int:
        """Merge two labels from the selected frame onward and return the survivor."""
        first, second = track_ids
        if first == second:
            raise ValueError("Choose two different tracks to merge.")
        frames = {track_id: self._frames_for(track_id, channel, z_index)
                  for track_id in track_ids}
        if any(not values for values in frames.values()):
            raise ValueError("Both selected tracks must exist in this channel and Z plane.")
        survivor = min(track_ids, key=lambda value: (min(frames[value]), value))
        replaced = second if survivor == first else first
        changed_frames = sorted(
            value for value in frames[replaced] if value >= frame_index)
        if not changed_frames:
            raise ValueError("The track being merged is not present from this frame onward.")
        self._remember_undo(channel, z_index, changed_frames)
        changed = self._replace_track_id(
            replaced, survivor, range(frame_index, self.frame_count), channel, z_index)
        if not changed:
            raise ValueError("The track being merged is not present from this frame onward.")
        self._invalidate_centroids(channel, z_index)
        self._has_edits = True
        self._record_edit("merge", channel)
        return survivor

    def link_tracks(self, track_ids: tuple[int, int], channel: int | str,
                    z_index: int) -> tuple[int, bool]:
        """Join two complete histories, using a new ID if their frames overlap."""
        first, second = track_ids
        if first == second:
            raise ValueError("Choose two different tracks to link.")
        frames = {track_id: self._frames_for(track_id, channel, z_index)
                  for track_id in track_ids}
        if any(not values for values in frames.values()):
            raise ValueError("Both selected tracks must exist in this channel and Z plane.")
        conflict = bool(frames[first].intersection(frames[second]))
        target = (self._next_track_id() if conflict else
                  min(track_ids, key=lambda value: (min(frames[value]), value)))
        self._remember_undo(
            channel, z_index, sorted(frames[first] | frames[second]))
        for track_id in track_ids:
            if track_id != target:
                self._replace_track_id(
                    track_id, target, range(self.frame_count), channel, z_index)
        self._invalidate_centroids(channel, z_index)
        self._has_edits = True
        self._record_edit("link", channel)
        return target, conflict

    def stop_track(self, track_id: int, frame_index: int,
                   channel: int | str, z_index: int) -> int:
        """End a track at one frame and relabel its later observations."""
        new_track_id = self._next_track_id()
        changed_frames = sorted(
            value for value in self._frames_for(track_id, channel, z_index)
            if value > frame_index)
        if not changed_frames:
            raise ValueError("This track has no observations after the current frame.")
        self._remember_undo(channel, z_index, changed_frames)
        changed = self._replace_track_id(
            track_id, new_track_id, range(frame_index + 1, self.frame_count),
            channel, z_index)
        if not changed:
            raise ValueError("This track has no observations after the current frame.")
        self._invalidate_centroids(channel, z_index)
        self._has_edits = True
        self._record_edit("stop", channel)
        return new_track_id

    def delete_track(self, track_id: int, channel: int | str, z_index: int) -> None:
        """Delete every mask belonging to one track in this channel and Z plane."""
        changed_frames = sorted(self._frames_for(track_id, channel, z_index))
        if not changed_frames:
            raise ValueError("The selected track has no masks in this channel and Z plane.")
        self._remember_undo(channel, z_index, changed_frames)
        for frame_index in changed_frames:
            labels = self.tracked_frame(frame_index, channel, z_index)
            labels[labels == track_id] = 0
        self._invalidate_centroids(channel, z_index)
        self._has_edits = True
        self._record_edit("delete-track", channel)

    def preview_split(self, track_id: int, frame_index: int,
                      channel: int | str, z_index: int,
                      *, image_channel: int | str | None = None,
                      guide: NDArray | None = None) -> dict[str, Any]:
        """Calculate a two-label preview without changing the tracking mask."""
        labels = self.tracked_frame(frame_index, channel, z_index)
        selected = labels == track_id
        if not np.any(selected):
            raise ValueError("The selected track has no mask in the current frame.")
        raw_channel: int | str = 0 if image_channel is None else image_channel
        image = (None if self.image_session is None else self.display_frame(
            frame_index, raw_channel, z_index))
        supporting_images = self._split_supporting_images(
            frame_index, raw_channel, z_index)
        proposal = self._split_predictor.predict(
            selected, image=image, supporting_images=supporting_images,
            guide=guide)
        keep_region = self._region_that_keeps_id(
            proposal.regions, track_id, frame_index, channel, z_index)
        if keep_region == 2:
            regions = proposal.regions.copy()
            first = regions == 1
            second = regions == 2
            regions[first] = 2
            regions[second] = 1
        else:
            regions = proposal.regions
        return {
            "track_id": track_id,
            "frame_index": frame_index,
            "channel": self._resolve_channel(channel),
            "z_index": z_index,
            "regions": regions,
            "gap": proposal.gap,
            "new_track_id": self._next_track_id(),
        }

    def _split_supporting_images(
            self, frame_index: int, image_channel: int | str,
            z_index: int) -> list[NDArray[Any]]:
        """Collect weak current-channel, cross-channel, and adjacent-frame evidence."""
        image_session = self.image_session
        if image_session is None:
            return []
        primary_label = (image_session.channel_labels[image_channel]
                         if isinstance(image_channel, int) else image_channel)
        supporting = [self.display_frame(frame_index, label, z_index)
                      for label in image_session.channel_labels
                      if label != primary_label]
        for adjacent in (frame_index - 1, frame_index + 1):
            if 0 <= adjacent < self.frame_count:
                supporting.append(self.display_frame(
                    adjacent, primary_label, z_index))
        return supporting

    def split_preview_labels(self, preview: dict[str, Any]) -> NDArray[Any]:
        """Return a display plane showing both proposed track IDs."""
        labels = self.tracked_frame(
            preview["frame_index"], preview["channel"], preview["z_index"]).copy()
        regions = preview["regions"]
        labels[preview["gap"]] = 0
        labels[regions == 1] = preview["track_id"]
        labels[regions == 2] = preview["new_track_id"]
        return labels

    def apply_split(self, preview: dict[str, Any]) -> int:
        """Commit a previously calculated split to its selected frame."""
        labels = self.tracked_frame(
            preview["frame_index"], preview["channel"], preview["z_index"])
        regions = preview["regions"]
        track_id = preview["track_id"]
        if not np.array_equal(labels == track_id, regions != 0):
            if not np.array_equal(labels == track_id, (regions != 0) | preview["gap"]):
                raise ValueError("The selected mask changed after this split was previewed.")
        new_track_id = self._next_track_id()
        self._remember_undo(
            preview["channel"], preview["z_index"], [preview["frame_index"]])
        labels[(regions != 0) | preview["gap"]] = 0
        labels[regions == 1] = track_id
        labels[regions == 2] = new_track_id
        self._invalidate_centroids(preview["channel"], preview["z_index"])
        self._has_edits = True
        self._record_edit("split", preview["channel"])
        return new_track_id

    def delete_mask(self, track_id: int, frame_index: int,
                    channel: int | str, z_index: int) -> None:
        """Delete one track mask from the current frame only."""
        labels = self.tracked_frame(frame_index, channel, z_index)
        selected = labels == track_id
        if not np.any(selected):
            raise ValueError("The selected track has no mask in the current frame.")
        self._remember_undo(channel, z_index, [frame_index])
        labels[selected] = 0
        self._invalidate_after_mask_edit(channel, z_index)
        self._record_edit("delete", channel)

    def preview_add_edit(
            self,
            track_id: int,
            frame_index: int,
            image_channel: int | str,
            mask_channel: int | str,
            z_index: int,
            positive_points: list[tuple[int, int]],
            negative_points: list[tuple[int, int]],
            expected_diameter: int,
            initial_mask: NDArray | None = None,
            excluded_mask: NDArray | None = None,
            manual_stroke: bool = False,
            continue_from_previous: bool = False,
            ) -> dict[str, Any]:
        """Build an Add/Edit preview with micro-SAM or a manual mask fill."""
        if self.image_session is None:
            raise ValueError("Local segmentation requires a sibling fits_array.tif image.")
        labels = self.tracked_frame(frame_index, mask_channel, z_index)
        replace_existing = bool(np.any(labels == track_id))
        occupied_mask = (labels != 0) & (labels != track_id)

        if manual_stroke:
            if initial_mask is None:
                raise ValueError("A manual mask is required before filling it.")
            proposal = fill_enclosed_mask(
                initial_mask, positive_points,
                expected_diameter=expected_diameter,
                occupied_mask=occupied_mask,
                excluded_mask=excluded_mask)
        else:
            image = self.display_frame(frame_index, image_channel, z_index)
            mask_prompt = (
                np.asarray(initial_mask, dtype=bool)
                if initial_mask is not None
                and (replace_existing or not positive_points)
                and np.any(initial_mask) else None)
            predictor_positive_points = list(positive_points)
            if mask_prompt is not None:
                coordinates = np.column_stack(np.nonzero(mask_prompt))
                centroid = np.round(np.mean(coordinates, axis=0)).astype(int)
                anchor = (int(centroid[0]), int(centroid[1]))
                if anchor not in predictor_positive_points:
                    predictor_positive_points.insert(0, anchor)
            prediction_context = (
                track_id, frame_index, self._resolve_channel(mask_channel), z_index)
            proposal = self._add_edit_backend.predict(
                image, predictor_positive_points, negative_points,
                initial_mask=mask_prompt, excluded_mask=excluded_mask,
                occupied_mask=occupied_mask,
                expected_diameter=expected_diameter,
                prediction_context=prediction_context,
                continue_from_previous=continue_from_previous)

            if (continue_from_previous and initial_mask is not None
                    and (positive_points or negative_points)):
                y0, y1, x0, x1 = proposal.bounds
                working = np.asarray(initial_mask[y0:y1, x0:x1], dtype=bool)
                candidate = np.asarray(proposal.mask, dtype=bool)
                rows, columns = np.ogrid[:candidate.shape[0], :candidate.shape[1]]
                positive_influence = np.zeros(candidate.shape, dtype=bool)
                negative_influence = np.zeros(candidate.shape, dtype=bool)
                positive_radius = max(
                    3.0, float(expected_diameter)
                    * MICROSAM_POSITIVE_REFINEMENT_RADIUS)
                negative_radius = max(
                    2.0, float(expected_diameter)
                    * MICROSAM_NEGATIVE_REFINEMENT_RADIUS)
                for point_y, point_x in positive_points:
                    local_y, local_x = point_y - y0, point_x - x0
                    positive_influence |= (
                        (rows - local_y) ** 2 + (columns - local_x) ** 2
                        <= positive_radius ** 2)
                for point_y, point_x in negative_points:
                    local_y, local_x = point_y - y0, point_x - x0
                    negative_influence |= (
                        (rows - local_y) ** 2 + (columns - local_x) ** 2
                        <= negative_radius ** 2)
                localized = working.copy()
                localized[positive_influence] |= candidate[positive_influence]
                localized[negative_influence] &= candidate[negative_influence]
                localized[np.asarray(
                    occupied_mask[y0:y1, x0:x1], dtype=bool)] = False
                if excluded_mask is not None:
                    localized[np.asarray(
                        excluded_mask[y0:y1, x0:x1], dtype=bool)] = False
                proposal = AddEditProposal(
                    mask=localized, bounds=proposal.bounds)

            self._add_edit_backend.synchronize_mask(
                proposal.mask, prediction_context)

        if not np.any(proposal.mask):
            raise ValueError("No connected foreground was found at the positive point.")
        return {
            "track_id": track_id,
            "frame_index": frame_index,
            "mask_channel": self._resolve_channel(mask_channel),
            "image_channel": image_channel,
            "z_index": z_index,
            "bounds": proposal.bounds,
            "mask": proposal.mask,
            "replace_existing": replace_existing,
        }

    def add_edit_preview_labels(self, preview: dict[str, Any]) -> NDArray[Any]:
        """Return labels with a local segmentation proposal inserted for display."""
        labels = self.tracked_frame(
            preview["frame_index"], preview["mask_channel"], preview["z_index"]).copy()
        y0, y1, x0, x1 = preview["bounds"]
        crop = labels[y0:y1, x0:x1]
        candidate = np.asarray(preview["mask"], dtype=bool)
        crop[candidate] = preview["track_id"]
        return labels

    def apply_add_edit(self, preview: dict[str, Any]) -> None:
        """Insert a new mask or replace the selected mask in the current frame."""
        labels = self.tracked_frame(
            preview["frame_index"], preview["mask_channel"], preview["z_index"])
        track_id = int(preview["track_id"])
        replace_existing = bool(preview.get("replace_existing", False))
        if np.any(labels == track_id) and not replace_existing:
            raise ValueError("This track already has a mask in the current frame.")
        y0, y1, x0, x1 = preview["bounds"]
        candidate = np.asarray(preview["mask"], dtype=bool)
        crop = labels[y0:y1, x0:x1]
        baseline_key = (
            int(preview["frame_index"]), int(preview["mask_channel"]),
            int(preview["z_index"]), track_id)
        baselines = getattr(self, "_original_add_edit_masks", None)
        if baselines is None:
            baselines = {}
            self._original_add_edit_masks = baselines
        baselines.setdefault(baseline_key, np.asarray(labels == track_id, dtype=bool).copy())
        # Do not silently overwrite masks belonging to another track.
        collision = candidate & (crop != 0) & (crop != track_id)
        if np.any(collision):
            candidate = candidate & ((crop == 0) | (crop == track_id))
        if not np.any(candidate):
            raise ValueError("The proposed mask only overlaps existing tracks.")
        self._remember_undo(
            preview["mask_channel"], preview["z_index"], [preview["frame_index"]])
        if replace_existing:
            labels[labels == track_id] = 0
        crop[candidate] = track_id
        self._invalidate_after_mask_edit(preview["mask_channel"], preview["z_index"])
        mask_channel = int(preview["mask_channel"])
        image_channel = preview["image_channel"]
        image_session = self.image_session
        if image_session is None:
            raise RuntimeError("Cannot record a prediction without its source image.")
        image_label = (image_session.channel_labels[image_channel]
                       if isinstance(image_channel, int) else str(image_channel))
        self._record_edit("edit" if replace_existing else "add", mask_channel)
        if not hasattr(self, "_prediction_channels"):
            self._prediction_channels = []
        channel_pair = {
            "mask_channel": self._channel_labels[mask_channel],
            "image_channel": image_label,
        }
        if channel_pair not in self._prediction_channels:
            self._prediction_channels.append(channel_pair)

    def next_track_id(self) -> int:
        """Return the next label available for a newly drawn track."""
        return self._next_track_id()

    def _registered_temporal_mask_prior(
            self, track_id: int, frame_index: int,
            image_channel: int | str, mask_channel: int | str, z_index: int,
            expected_diameter: float,
            ) -> tuple[NDArray[np.bool_] | None, tuple[float, float], float]:
        """Register the nearest earlier track mask onto the current image."""
        if frame_index <= 0:
            return None, (0.0, 0.0), 0.0
        previous_frame = None
        previous_mask = None
        for candidate_frame in range(frame_index - 1, -1, -1):
            candidate = self.tracked_frame(
                candidate_frame, mask_channel, z_index) == track_id
            if np.any(candidate):
                previous_frame = candidate_frame
                previous_mask = candidate
                break
        if previous_frame is None or previous_mask is None:
            return None, (0.0, 0.0), 0.0
        registered, shift, confidence = _register_mask_translation(
            self.display_frame(previous_frame, image_channel, z_index),
            self.display_frame(frame_index, image_channel, z_index),
            previous_mask, expected_diameter)
        if confidence <= 0.0:
            return None, shift, confidence
        labels = self.tracked_frame(frame_index, mask_channel, z_index)
        registered[(labels != 0) & (labels != track_id)] = False
        return registered, shift, confidence

    def _invalidate_after_mask_edit(self, channel: int | str, z_index: int) -> None:
        self._invalidate_centroids(channel, z_index)
        self._has_edits = True

    @property
    def can_undo(self) -> bool:
        """Return whether an accepted tracking edit can be restored."""
        return bool(getattr(self, "_undo_history", []))

    def undo_last_edit(self) -> int | None:
        """Restore the planes and edit metadata preceding the latest accepted edit."""
        history = getattr(self, "_undo_history", [])
        if not history:
            return None
        entry = history.pop()
        for frame, plane in zip(entry.frames, entry.planes, strict=True):
            self.tracked_frame(frame, entry.channel, entry.z_index)[...] = plane
        self._has_edits = entry.has_edits
        self._operations_used = set(entry.operations_used)
        self._edited_mask_channels = set(entry.edited_mask_channels)
        self._prediction_channels = [dict(pair) for pair in entry.prediction_channels]
        self._invalidate_centroids(entry.channel, entry.z_index)
        return min(entry.frames) if entry.frames else None

    def _remember_undo(self, channel: int | str, z_index: int,
                       frames: list[int]) -> None:
        """Store only affected 2D planes, avoiding copies of the complete movie."""
        unique_frames = tuple(sorted(set(frames)))
        if not unique_frames:
            return
        channel_index = self._resolve_channel(channel)
        entry = _TrackingUndo(
            channel=channel_index,
            z_index=z_index,
            frames=unique_frames,
            planes=tuple(self.tracked_frame(
                frame, channel_index, z_index).copy() for frame in unique_frames),
            has_edits=getattr(self, "_has_edits", False),
            operations_used=frozenset(getattr(self, "_operations_used", set())),
            edited_mask_channels=frozenset(
                getattr(self, "_edited_mask_channels", set())),
            prediction_channels=tuple(
                dict(pair) for pair in getattr(self, "_prediction_channels", [])),
        )
        if not hasattr(self, "_undo_history"):
            self._undo_history = []
        self._undo_history.append(entry)
        del self._undo_history[:-50]

    def _record_edit(self, operation: str, channel: int | str) -> None:
        if not hasattr(self, "_operations_used"):
            self._operations_used = set()
        if not hasattr(self, "_edited_mask_channels"):
            self._edited_mask_channels = set()
        self._operations_used.add(operation)
        self._edited_mask_channels.add(self._resolve_channel(channel))

    def _region_that_keeps_id(self, regions: NDArray, track_id: int,
                              frame_index: int, channel: int | str,
                              z_index: int) -> int:
        centroids = self.track_centroids(channel, z_index).get(track_id)
        previous = (centroids[centroids[:, 0] < frame_index]
                    if centroids is not None else np.empty((0, 3)))
        if len(previous):
            target = previous[-1, [2, 1]]
            distances = []
            for region in (1, 2):
                center = np.mean(np.column_stack(np.nonzero(regions == region)), axis=0)
                distances.append(float(np.linalg.norm(center - target)))
            return int(np.argmin(distances)) + 1
        sizes = [np.count_nonzero(regions == region) for region in (1, 2)]
        return int(np.argmax(sizes)) + 1

    def _frames_for(self, track_id: int, channel: int | str,
                    z_index: int) -> set[int]:
        return {frame for frame in range(self.frame_count)
                if np.any(self.tracked_frame(frame, channel, z_index) == track_id)}

    def _replace_track_id(self, source: int, target: int, frames: range,
                          channel: int | str, z_index: int) -> bool:
        changed = False
        for frame in frames:
            labels = self.tracked_frame(frame, channel, z_index)
            selected = labels == source
            if np.any(selected):
                labels[selected] = target
                changed = True
        return changed

    def _invalidate_centroids(self, channel: int | str, z_index: int) -> None:
        self._centroid_cache.pop((self._resolve_channel(channel), z_index), None)

    def _next_track_id(self) -> int:
        next_id = int(np.max(self._tracks, initial=0)) + 1
        if np.issubdtype(self._tracks.dtype, np.integer):
            if next_id > np.iinfo(self._tracks.dtype).max:
                raise ValueError("No unused track IDs remain in this label data type.")
        return next_id

    def save_rendered_display(self,
                              *,
                              label: str,
                              channel: int | str,
                              z_index: int,
                              show_paths: bool,
                              path_extent: str,
                              thickness: int,
                              show_centroids: bool,
                              marker_size: int,
                              path_color_mode: str,
                              path_color: str,
                              mask_visible: bool,
                              mask_opacity: float,
                              track_ids: frozenset[int] | None,
                              filtered: bool,
                              display_metadata: dict[str, Any],
                              ) -> Path:
        """

        Render and save an RGB tracking visualization.

        """
        normalized_label = self._validate_output_label(label)
        qualifier = "filtered_" if filtered else ""
        output_path = self.source_path.with_name(
            f"fits_track_{qualifier}{normalized_label}.tif")
        selected_channel = self._resolve_channel(channel)
        output = render_selected_tracking_display(
                                        frame_count=self.frame_count,
                                        selected_channel=selected_channel,
                                        selected_z=z_index,
                                        tracked_frame=self.tracked_frame,
                                        centroids=self.track_centroids(selected_channel, z_index),
                                        show_paths=show_paths,
                                        path_extent=path_extent,
                                        thickness=thickness,
                                        show_centroids=show_centroids,
                                        marker_size=marker_size,
                                        path_color_mode=path_color_mode,
                                        path_color=path_color,
                                        mask_visible=mask_visible,
                                        mask_opacity=mask_opacity,
                                        track_ids=track_ids,)
        metadata = {"tracking_viewer_display": display_metadata}
        payload = self._reader.build_payload(export_channels=self._channel_labels,
                                            artifact_type="tracking_visualization",
                                            created_by=DIST_FITS,
                                            custom_metadata=metadata,
                                            ).with_fitsio(
                                                axes="TYXS" if self.frame_count > 1 else "YXS")
        return self._reader.save_array(output, metadata=payload, output_path=output_path)

    def save_edited_tracking(self,
                             *,
                             filter_spec: dict[str, Any] | None = None,
                             filter_condition: dict[str, Any] | None = None,
                             pipeline_metadata: dict[str, Any] | None = None,
                             selected_mask_channel: int | str | None = None,
                             ) -> tuple[Path, dict[str, Any]]:
        """Save the current labels as a downstream-compatible tracking artifact."""
        filtered = filter_spec is not None
        output_name = (FITS_MASK_TRACK_EDITED_FILTERED if filtered
                       else FITS_MASK_TRACK_EDITED)
        output_path = self.source_path.with_name(output_name)
        output = self._filtered_tracking_array(filter_spec) if filtered else self._tracks.copy()
        mask_channel_indices = set(self._edited_mask_channels)
        if filtered:
            mask_channel_indices.update(range(self._axis_size("C")))
        if not mask_channel_indices and selected_mask_channel is not None:
            mask_channel_indices.add(self._resolve_channel(selected_mask_channel))
        prediction_channels = [
            pair for index, pair in enumerate(self._prediction_channels)
            if pair not in self._prediction_channels[:index]
        ]
        metadata = {
            "source_tracking_artifact": self.source_path.name,
            "mask_channels": [self._channel_labels[index]
                              for index in sorted(mask_channel_indices)],
            "prediction_image_channels": prediction_channels,
            "operations_used": sorted(self._operations_used),
            "filter_condition": filter_condition,
            "timestamp": utc_now(),
            "fits_version": distribution_version(DIST_FITS),
        }
        fits_metadata = (FitsMeta.from_dict(pipeline_metadata)
                         if pipeline_metadata else FitsMeta.init())
        custom_metadata = fits_metadata.with_step(
            step_name=StepName.EDIT_TRACK,
            created_by=DIST_FITS,
            exported_channel="all",
            params=metadata,
        ).to_dict()
        payload = self._reader.build_payload(
            export_channels=self._channel_labels,
            artifact_type="tracking",
            created_by=DIST_FITS,
            custom_metadata=custom_metadata,
        ).with_fitsio(axes=self._axes)
        saved = self._reader.save_array(
            output, metadata=payload, output_path=output_path)
        return saved, metadata

    def _filtered_tracking_array(self,
                                 filter_spec: dict[str, Any] | None,
                                 ) -> NDArray[Any]:
        if filter_spec is None:
            return self._tracks.copy()
        output = self._tracks.copy()
        operator = str(filter_spec["operator"])
        value = int(filter_spec["value"])
        maximum = filter_spec.get("maximum")
        maximum = int(maximum) if maximum is not None else None
        for channel in range(self._axis_size("C")):
            for z_index in range(self._axis_size("Z")):
                retained = self.track_ids_matching(
                    channel, z_index, operator, value, maximum)
                for frame in range(self.frame_count):
                    selection = self._plane_selection(frame, channel, z_index)
                    labels = output[selection]
                    labels[~np.isin(labels, tuple(retained))] = 0
        return output

    def _plane_selection(self, frame_index: int, channel_index: int, z_index: int,) -> tuple[int | slice, ...]:
        """

        Build an index for one frame, channel, and Z plane.

        """
        selection: list[int | slice] = [slice(None)] * self._tracks.ndim
        for axis, value in (("T", frame_index),
                            ("C", channel_index),
                            ("Z", z_index),):
            if axis in self._axes:
                selection[self._axes.index(axis)] = value
        return tuple(selection)

    @staticmethod
    def _validate_output_label(label: str) -> str:
        """

        Validate and normalize a tracking-display output label.

        """
        normalized = label.strip() or "path"
        invalid = frozenset('<>:"/\\|?*').intersection(normalized)
        if normalized.endswith(".") or invalid or any(ord(char) < 32 for char in normalized):
            raise ValueError(f"Invalid tracking display label: {label!r}.")
        return normalized

    def _resolve_channel(self, channel: int | str) -> int:
        """

        Resolve a tracking channel index or label.

        """
        if isinstance(channel, int):
            return channel
        return self._channel_labels.index(channel)

    def _axis_size(self, axis: str) -> int:
        """

        Return an axis size, defaulting to one when absent.

        """
        if axis not in self._axes:
            return 1
        return self._tracks.shape[self._axes.index(axis)]
