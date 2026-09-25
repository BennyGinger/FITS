"""Complete missing observations in trustworthy static-cell tracks."""

import numpy as np
from mask_interpolation import fill_missing_masks
from numpy.typing import NDArray

from fits.tasks.tracking.static_masks.identities import track_labels


def complete_tracks(filtered: NDArray[np.generic],
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
            candidate &= completed[frame_index] == 0
            completed[frame_index][candidate] = label

    # The old routine performed a second trim after collision clipping. Apply
    # it to the interval this configuration actually requested: a track which
    # could not be completed without crossing another cell is removed instead
    # of surviving as a partial streak.
    for label in track_labels(filtered):
        observed = np.flatnonzero(np.any(filtered == label, axis=(1, 2)))
        required_start = 0 if extrapolate_start else int(observed[0])
        required_end = filtered.shape[0] if extrapolate_end else int(observed[-1]) + 1
        if not np.all(np.any(completed[required_start:required_end] == label,
                            axis=(1, 2))):
            completed[completed == label] = 0
    return completed
