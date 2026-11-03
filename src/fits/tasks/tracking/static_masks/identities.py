"""Reconnect changing track labels using their stable spatial identities."""

import numpy as np
from numpy.typing import NDArray


def track_labels(masks: NDArray[np.generic]) -> NDArray[np.generic]:
    """
    Return the unique nonzero labels in a mask array.
    """
    labels = np.unique(masks)
    return labels[labels != 0]


def build_temporal_supermask(masks: NDArray[np.generic],) -> NDArray[np.generic]:
    """
    Return the most frequent consistent identity at every spatial pixel.

    A label must occupy a pixel in at least half of its observed frames. This
    prevents one expanded outlier from enlarging the reference for every frame.
    """
    mode = np.zeros(masks.shape[1:], dtype=masks.dtype)
    largest_count = np.zeros(masks.shape[1:], dtype=np.intp)
    for label in track_labels(masks):
        track = masks == label
        count = np.count_nonzero(track, axis=0)
        appearances = np.count_nonzero(np.any(track, axis=(1, 2)))
        replace = (count > largest_count) & (2 * count >= appearances)
        mode[replace] = label
        largest_count[replace] = count[replace]
    return mode


def reconnect_identities(masks: NDArray[np.generic],
                         supermask: NDArray[np.generic],
                         *,
                         minimum_iou: float = 0.5,
                         ) -> NDArray[np.generic]:
    """
    Map confident observations to the temporal supermask, leaving doubtful ones empty.
    """
    reconnected = np.zeros_like(masks)
    super_areas = _label_areas(supermask)
    for frame_index, frame in enumerate(masks):
        for label in track_labels(frame):
            frame_object = frame == label
            identity = _unique_best_supermask_label(frame_object,
                                                   supermask,
                                                   super_areas,
                                                   minimum_iou=minimum_iou,
                                                   )
            if identity is not None:
                reconnected[frame_index][frame_object] = identity
    return reconnected


def _label_areas(mask: NDArray[np.generic]) -> dict[int, int]:
    """
    Return the pixel area occupied by every nonzero label.
    """
    return {int(label): int(np.count_nonzero(mask == label))
            for label in track_labels(mask)}


def _overlap_counts(frame_object: NDArray[np.bool_], supermask: NDArray[np.generic],) -> dict[int, int]:
    """
    Count object pixels overlapping each supermask identity.
    """
    labels, counts = np.unique(supermask[frame_object], return_counts=True)
    return {int(label): int(count)
            for label, count in zip(labels, counts, strict=True)
            if label != 0}


def _unique_best_supermask_label(frame_object: NDArray[np.bool_],
                                 supermask: NDArray[np.generic],
                                 super_areas: dict[int, int],
                                 *,
                                 minimum_iou: float,
                                 ) -> int | None:
    """
    Return the unique best identity only when its overlap meets the required IoU.
    """
    intersections = _overlap_counts(frame_object, supermask)
    if not intersections:
        return None
    
    object_area = int(np.count_nonzero(frame_object))
    scores = {label: intersection / (object_area + super_areas[label] - intersection)
                for label, intersection in intersections.items()}
    best_score = max(scores.values())
    if best_score < minimum_iou:
        return None
    best_labels = [label for label, score in scores.items()
                    if np.isclose(score, best_score)]
    return best_labels[0] if len(best_labels) == 1 else None
