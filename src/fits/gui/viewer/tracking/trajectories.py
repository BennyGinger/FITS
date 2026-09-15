"""Centroid extraction and trajectory rasterisation for tracked labels."""

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from skimage.draw import disk as raster_disk, line as raster_line
from skimage.morphology import dilation, disk as disk_footprint


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


def rasterize_path(points: NDArray[np.float64],
                    shape: tuple[int, int],
                    thickness: int,
                    show_centroids: bool,
                    ) -> NDArray[np.bool_]:
    """
    Rasterize a centroid trajectory into a boolean image mask. 
    """
    canvas = np.zeros(shape, dtype=bool)
    rounded = (np.rint(points[:, [2, 1]]).astype(int)
                if len(points) else np.empty((0, 2), int))
    
    for start, end in zip(rounded[:-1], rounded[1:], strict=True):
        rows, columns = raster_line(start[0], start[1], end[0], end[1])
        valid = ((rows >= 0) & (rows < shape[0])
                    & (columns >= 0) & (columns < shape[1]))
        canvas[rows[valid], columns[valid]] = True
    radius = max(0, int(thickness) // 2)
    if radius:
        canvas = dilation(canvas, disk_footprint(radius))
    if show_centroids:
        marker_radius = max(2, radius + 1)
        for row, column in rounded:
            rows, columns = raster_disk(
                (row, column), marker_radius, shape=shape)
            canvas[rows, columns] = True
    return canvas
