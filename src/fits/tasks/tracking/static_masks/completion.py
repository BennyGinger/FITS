"""Complete missing observations in trustworthy static-cell tracks."""

import numpy as np
from mask_interpolation import fill_missing_masks
from numpy.typing import NDArray

from fits.tasks.tracking.static_masks.identities import track_labels


def complete_tracks(filtered: NDArray[np.generic],
                    supermask: NDArray[np.generic],
                    *,
                    extrapolate_start: bool,
                    extrapolate_end: bool,
                    ) -> NDArray[np.generic]:
    """
    Interpolate track gaps and optionally extrapolate their endpoints.
    """
    completed = filtered.copy()
    for label in track_labels(filtered):
        single_track = np.where(filtered == label, label, 0).astype(filtered.dtype, copy=False)
        observed = np.any(single_track != 0, axis=(1, 2))
        if np.all(observed):
            continue
        interpolated = fill_missing_masks(single_track,
                                        axes="TYX",
                                        interpolation_axis="T",
                                        extrapolate_start=extrapolate_start,
                                        extrapolate_end=extrapolate_end,)
        for frame_index, candidate in enumerate(interpolated == label):
            if observed[frame_index]:
                continue
            occupied = (completed[frame_index] != 0) & candidate
            if np.any(occupied):
                candidate = supermask == label
            candidate &= completed[frame_index] == 0
            completed[frame_index][candidate] = label
    return completed
