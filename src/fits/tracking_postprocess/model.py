"""Post-processing for static-cell track masks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

import numpy as np
from mask_interpolation import fill_missing_masks
from numpy.typing import NDArray


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StaticPostprocessConfig:
    """Settings for static-cell track cleanup.

    ``minimum_appearances`` is evaluated after shape outliers are removed.
    Endpoint extrapolation copies the nearest trustworthy mask, matching the
    behavior of the historical pipeline.
    """

    shape_similarity: float = 0.9
    minimum_appearances: int = 5
    extrapolate_start: bool = True
    extrapolate_end: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.shape_similarity <= 1:
            raise ValueError("shape_similarity must be between 0 and 1.")
        if self.minimum_appearances < 1:
            raise ValueError("minimum_appearances must be at least 1.")


class StaticMaskPostprocessor:
    """Remove inconsistent masks and complete tracks of static cells."""

    def __init__(self, config: StaticPostprocessConfig | None = None) -> None:
        self.config = config or StaticPostprocessConfig()

    def process(self, masks: NDArray[np.generic]) -> NDArray[np.generic]:
        """Return a cleaned copy of a ``TYX`` stable-label mask movie.

        A temporal nonzero-mode supermask first restores the dominant static
        identity at each cell position. For each resulting track, a temporal
        consensus mask is calculated from frames in which the label is
        observed. Frames whose masks fall below the Dice similarity threshold
        are removed. Tracks with too few remaining observations are discarded.
        Missing masks are then completed by the ``mask-interpolation`` package.
        """
        _validate_masks(masks)
        supermask = _nonzero_mode(masks)
        reconnected = self._reconnect_with_supermask(masks, supermask)
        filtered = self._filter_tracks(reconnected)
        return self._complete_tracks(filtered, supermask)

    def _reconnect_with_supermask(self,
                                  masks: NDArray[np.generic],
                                  supermask: NDArray[np.generic],
                                  ) -> NDArray[np.generic]:
        """Map frame masks to identities in a temporal nonzero-mode supermask."""
        reconnected = masks.copy()
        super_areas = _label_areas(supermask)

        for frame_index, frame in enumerate(masks):
            for label in _track_labels(frame):
                frame_object = frame == label
                identity = _unique_best_supermask_label(
                    frame_object, supermask, super_areas)
                if identity is not None:
                    reconnected[frame_index][frame_object] = identity
        return reconnected

    def _filter_tracks(self, masks: NDArray[np.generic]) -> NDArray[np.generic]:
        filtered = np.zeros_like(masks)
        for label in _track_labels(masks):
            track = masks == label
            observed = np.any(track, axis=(1, 2))
            known_masks = track[observed]
            consensus = np.median(known_masks, axis=0) > 0
            similarities = np.array([
                _dice_similarity(consensus, frame)
                for frame in known_masks
            ])
            trustworthy_frames = np.flatnonzero(observed)[
                similarities >= self.config.shape_similarity]

            if trustworthy_frames.size < self.config.minimum_appearances:
                continue
            filtered[trustworthy_frames] = np.where(
                track[trustworthy_frames], label, filtered[trustworthy_frames])
        return filtered

    def _complete_tracks(self,
                         filtered: NDArray[np.generic],
                         supermask: NDArray[np.generic],
                         ) -> NDArray[np.generic]:
        labels = _track_labels(filtered)
        # Preserve every trustworthy observed mask before generating anything.
        # Otherwise an extrapolated low-numbered label can block a real mask
        # belonging to a label processed later.
        completed = filtered.copy()
        for label in labels:
            single_track = np.where(filtered == label, label, 0).astype(
                filtered.dtype, copy=False)
            observed = np.any(single_track != 0, axis=(1, 2))
            if np.all(observed):
                continue
            interpolated = fill_missing_masks(
                single_track,
                axes="TYX",
                interpolation_axis="T",
                extrapolate_start=self.config.extrapolate_start,
                extrapolate_end=self.config.extrapolate_end,)

            for frame_index, candidate in enumerate(interpolated == label):
                if observed[frame_index]:
                    continue
                occupied = (completed[frame_index] != 0) & candidate
                if np.any(occupied):
                    # Clipping an interpolated mask leaves a halo around its
                    # neighbour. For a static cell, its disjoint temporal-mode
                    # shape is a safer fallback for this frame.
                    candidate = supermask == label
                candidate &= completed[frame_index] == 0
                completed[frame_index][candidate] = label
        return completed


def _validate_masks(masks: NDArray[np.generic]) -> None:
    if not isinstance(masks, np.ndarray):
        logger.error("Static track post-processing requires a NumPy array.")
        raise TypeError("masks must be a NumPy array.")
    if masks.ndim != 3:
        logger.error("Expected a TYX mask movie, received shape %s.", masks.shape)
        raise ValueError(f"masks must have TYX dimensions; got shape {masks.shape}.")
    if 0 in masks.shape:
        logger.error("Static track post-processing received an empty dimension.")
        raise ValueError("masks cannot contain an empty dimension.")
    if not np.issubdtype(masks.dtype, np.integer) or masks.dtype == np.bool_:
        logger.error("Tracked masks require an integer dtype; received %s.", masks.dtype)
        raise TypeError(f"masks must use an integer dtype; got {masks.dtype}.")
    integer_masks = cast(NDArray[np.integer], masks)
    if np.any(integer_masks < 0):
        logger.error("Tracked masks contain negative labels.")
        raise ValueError("masks cannot contain negative labels.")


def _track_labels(masks: NDArray[np.generic]) -> NDArray[np.generic]:
    labels = np.unique(masks)
    return labels[labels != 0]


def _label_areas(mask: NDArray[np.generic]) -> dict[int, int]:
    """Return the pixel area occupied by each nonzero label."""
    return {int(label): int(np.count_nonzero(mask == label))
            for label in _track_labels(mask)}


def _overlap_counts(frame_object: NDArray[np.bool_],
                    supermask: NDArray[np.generic],
                    ) -> dict[int, int]:
    """Count the object's pixels overlapping each supermask identity."""
    labels, counts = np.unique(supermask[frame_object], return_counts=True)
    return {int(label): int(count)
            for label, count in zip(labels, counts, strict=True)
            if label != 0 }


def _unique_best_supermask_label(frame_object: NDArray[np.bool_],
                                 supermask: NDArray[np.generic],
                                 super_areas: dict[int, int],
                                 ) -> int | None:
    """Return the sole supermask identity with the highest IoU."""
    intersections = _overlap_counts(frame_object, supermask)
    if not intersections:
        return None

    object_area = int(np.count_nonzero(frame_object))
    scores = {
        label: intersection
        / (object_area + super_areas[label] - intersection)
        for label, intersection in intersections.items()
    }
    best_score = max(scores.values())
    best_labels = [
        label for label, score in scores.items()
        if np.isclose(score, best_score)
    ]
    return best_labels[0] if len(best_labels) == 1 else None


def _nonzero_mode(masks: NDArray[np.generic]) -> NDArray[np.generic]:
    """Return the most frequent nonzero label at each spatial pixel."""
    mode = np.zeros(masks.shape[1:], dtype=masks.dtype)
    largest_count = np.zeros(masks.shape[1:], dtype=np.intp)
    # Labels are sorted; retaining the first on ties matches scipy.stats.mode.
    for label in _track_labels(masks):
        count = np.count_nonzero(masks == label, axis=0)
        replace = count > largest_count
        mode[replace] = label
        largest_count[replace] = count[replace]
    return mode


def _dice_similarity(first: NDArray[np.bool_], second: NDArray[np.bool_]) -> float:
    size = int(first.sum() + second.sum())
    if size == 0:
        return 1.0
    intersection = int(np.count_nonzero(first & second))
    return 2 * intersection / size
