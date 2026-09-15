"""Remove unreliable observations and short static-cell tracks."""

import numpy as np
from numpy.typing import NDArray

from fits.tasks.tracking.static_masks.identities import track_labels


def filter_tracks(masks: NDArray[np.generic],
                    *,
                    shape_similarity: float,
                    minimum_appearances: int,
                    ) -> NDArray[np.generic]:
    """
    Keep tracks with enough observations matching their consensus shape.
    """
    filtered = np.zeros_like(masks)
    for label in track_labels(masks):
        track = masks == label
        observed = np.any(track, axis=(1, 2))
        known_masks = track[observed]
        consensus = np.median(known_masks, axis=0) > 0
        similarities = np.array([_dice_similarity(consensus, frame) 
                                 for frame in known_masks])
        trustworthy_frames = np.flatnonzero(observed)[
            similarities >= shape_similarity]
        if trustworthy_frames.size < minimum_appearances:
            continue
        filtered[trustworthy_frames] = np.where(track[trustworthy_frames], 
                                                label, 
                                                filtered[trustworthy_frames])
    return filtered


def _dice_similarity(first: NDArray[np.bool_], second: NDArray[np.bool_],) -> float:
    """
    Return the Dice similarity coefficient for two boolean masks.
    """
    size = int(first.sum() + second.sum())
    if size == 0:
        return 1.0
    intersection = int(np.count_nonzero(first & second))
    return 2 * intersection / size
