"""Artifact loading and navigation for the tracking viewer."""

from __future__ import annotations

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
from fits.tasks.tracking.mask_prediction import (
    AddEditPredictor,
    SplitPredictor,
    combine_auxiliary_masks,
    mask_agreement,
)
from fits.workflows.metadata._values import distribution_version, utc_now
from fits.workflows.metadata import FitsMeta


class TrackingViewerSession:
    """

    Load and navigate a tracked-label artifact and optional sibling image.

    """

    def __init__(self, tracking_path: str | Path,
                 image_path: str | Path | None = None) -> None:
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
        self._add_edit_predictor_cache: dict[tuple[str, int, int], AddEditPredictor] = {}
        self._split_predictor = SplitPredictor()
        self._has_edits = False
        self._operations_used: set[str] = set()
        self._edited_mask_channels: set[int] = set()
        self._prediction_channels: list[dict[str, str]] = []
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
        changed = self._replace_track_id(
            track_id, new_track_id, range(frame_index + 1, self.frame_count),
            channel, z_index)
        if not changed:
            raise ValueError("This track has no observations after the current frame.")
        self._invalidate_centroids(channel, z_index)
        self._has_edits = True
        self._record_edit("stop", channel)
        return new_track_id

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
        proposal = self._split_predictor.predict(
            selected, image=image, guide=guide)
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
            "method": proposal.method,
            "new_track_id": self._next_track_id(),
        }

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
            ) -> dict[str, Any]:
        """Predict a new or replacement mask from image evidence and prompts."""
        if self.image_session is None:
            raise ValueError("Local segmentation requires a sibling fits_array.tif image.")
        labels = self.tracked_frame(frame_index, mask_channel, z_index)
        replace_existing = bool(np.any(labels == track_id))
        model = self._add_edit_predictor(
            image_channel, mask_channel, z_index, frame_index=frame_index,
            positive_points=positive_points, negative_points=negative_points,
            expected_diameter=expected_diameter)
        auxiliary_masks, auxiliary_weights = self._auxiliary_mask_priors(
            frame_index, mask_channel, z_index)
        auxiliary, weight = combine_auxiliary_masks(auxiliary_masks, auxiliary_weights)
        temporal, temporal_weight = self._temporal_mask_prior(
            track_id, frame_index, mask_channel, z_index, positive_points[0])
        image = self.display_frame(frame_index, image_channel, z_index)
        proposal = model.predict(
            image, positive_points, negative_points,
            auxiliary_mask=auxiliary, auxiliary_weight=weight,
            temporal_mask=temporal, temporal_weight=temporal_weight,
            initial_mask=initial_mask, excluded_mask=excluded_mask)
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
            "auxiliary_weight": proposal.auxiliary_weight,
            "temporal_weight": proposal.temporal_weight,
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
        # Do not silently overwrite masks belonging to another track.
        collision = candidate & (crop != 0) & (crop != track_id)
        if np.any(collision):
            candidate = candidate & ((crop == 0) | (crop == track_id))
        if not np.any(candidate):
            raise ValueError("The proposed mask only overlaps existing tracks.")
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

    def _add_edit_predictor(self, image_channel: int | str,
                                  mask_channel: int | str,
                                  z_index: int,
                                  *,
                                  frame_index: int,
                                  positive_points: list[tuple[int, int]],
                                  negative_points: list[tuple[int, int]],
                                  expected_diameter: int,
                                  ) -> AddEditPredictor:
        image_session = self.image_session
        if image_session is None:
            raise ValueError("Local segmentation requires a sibling fits_array.tif image.")
        image_label = (image_session.channel_labels[image_channel]
                       if isinstance(image_channel, int) else image_channel)
        mask_index = self._resolve_channel(mask_channel)
        key = (image_label, mask_index, z_index)
        cached = self._add_edit_predictor_cache.get(key)
        if cached is not None:
            return cached
        if getattr(self, "_started_from_image", False) and not self._has_edits:
            model = AddEditPredictor()
            model.fit_from_prompts(
                self.display_frame(frame_index, image_channel, z_index),
                positive_points, negative_points, expected_diameter)
            self._add_edit_predictor_cache[key] = model
            return model
        # A representative subset keeps the first fit responsive on long movies.
        count = min(self.frame_count, 12)
        frames = np.unique(np.linspace(0, self.frame_count - 1, count, dtype=int))
        images = [self.display_frame(int(frame), image_channel, z_index) for frame in frames]
        masks = [self.tracked_frame(int(frame), mask_index, z_index) for frame in frames]
        model = AddEditPredictor()
        try:
            model.fit(images, masks)
        except ValueError as error:
            if "foreground" not in str(error) and "segmented objects" not in str(error):
                raise
            populated = [frame for frame in range(self.frame_count)
                         if np.any(self.tracked_frame(frame, mask_index, z_index))]
            if not populated:
                model.fit_from_prompts(
                    self.display_frame(frame_index, image_channel, z_index),
                    positive_points, negative_points, expected_diameter)
                self._add_edit_predictor_cache[key] = model
                return model
            selected = np.asarray(populated)[np.unique(np.linspace(
                0, len(populated) - 1, min(len(populated), 12), dtype=int))]
            images = [self.display_frame(int(frame), image_channel, z_index)
                      for frame in selected]
            masks = [self.tracked_frame(int(frame), mask_index, z_index)
                     for frame in selected]
            model.fit(images, masks)
        self._add_edit_predictor_cache[key] = model
        return model

    def next_track_id(self) -> int:
        """Return the next label available for a newly drawn track."""
        return self._next_track_id()

    def _auxiliary_mask_priors(self, frame_index: int, mask_channel: int | str,
                               z_index: int) -> tuple[list[NDArray], list[float]]:
        target_index = self._resolve_channel(mask_channel)
        if self._axis_size("C") <= 1:
            return [], []
        count = min(self.frame_count, 12)
        frames = np.unique(np.linspace(0, self.frame_count - 1, count, dtype=int))
        target_training = [self.tracked_frame(int(frame), target_index, z_index)
                           for frame in frames]
        masks: list[NDArray] = []
        weights: list[float] = []
        for auxiliary_index in range(self._axis_size("C")):
            if auxiliary_index == target_index:
                continue
            auxiliary_training = [
                self.tracked_frame(int(frame), auxiliary_index, z_index)
                for frame in frames]
            weight = mask_agreement(target_training, auxiliary_training)
            if weight >= 0.1:
                masks.append(self.tracked_frame(frame_index, auxiliary_index, z_index) != 0)
                weights.append(weight)
        return masks, weights

    def _temporal_mask_prior(self, track_id: int, frame_index: int,
                             mask_channel: int | str, z_index: int,
                             anchor: tuple[int, int],
                             ) -> tuple[NDArray[np.bool_] | None, float]:
        """Translate the nearest earlier mask toward the current positive click."""
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
            return None, 0.0
        coordinates = np.column_stack(np.nonzero(previous_mask))
        center_y, center_x = np.mean(coordinates, axis=0)
        shift_y = int(round(anchor[0] - center_y))
        shift_x = int(round(anchor[1] - center_x))
        translated = np.zeros_like(previous_mask, dtype=bool)
        source_y, source_x = np.nonzero(previous_mask)
        target_y = source_y + shift_y
        target_x = source_x + shift_x
        valid = ((target_y >= 0) & (target_y < translated.shape[0])
                 & (target_x >= 0) & (target_x < translated.shape[1]))
        translated[target_y[valid], target_x[valid]] = True
        gap = frame_index - previous_frame
        weight = 0.9 / (1.0 + 0.25 * max(0, gap - 1))
        return translated, weight

    def _invalidate_after_mask_edit(self, channel: int | str, z_index: int) -> None:
        self._invalidate_centroids(channel, z_index)
        self._has_edits = True

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
