"""Centroid extraction for tracked labels."""

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray


def calculate_track_centroids(tracked_frame: Callable[[int, int, int], NDArray],
                                *,
                                frame_count: int,
                                channel_index: int,
                                z_index: int,
                                ) -> dict[int, NDArray[np.float64]]:
    """
    Return ``(frame, x, y)`` centroid observations for each nonzero track.
    """
    observations: dict[int, list[tuple[float, float, float]]] = {}
    for frame_index in range(frame_count):
        labels = np.asarray(tracked_frame(frame_index, channel_index, z_index))
        present, inverse = np.unique(labels, return_inverse=True)
        inverse = inverse.ravel()
        rows, columns = np.indices(labels.shape)
        counts = np.bincount(inverse)
        row_sums = np.bincount(inverse, weights=rows.ravel())
        column_sums = np.bincount(inverse, weights=columns.ravel())
        for position, label in enumerate(present):
            track_id = int(label)
            if track_id == 0:
                continue
            observations.setdefault(track_id, []).append((float(frame_index),
                                                    float(column_sums[position] / counts[position]),
                                                    float(row_sums[position] / counts[position]),))
    return {track_id: np.asarray(points, dtype=np.float64)
            for track_id, points in observations.items()}
