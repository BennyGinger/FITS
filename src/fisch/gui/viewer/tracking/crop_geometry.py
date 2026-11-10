"""Automatic track bounds and clipping in image pixel coordinates."""

from collections.abc import Callable
from math import ceil
from typing import Any

import numpy as np
from numpy.typing import NDArray


CropBounds = tuple[int, int, int, int]  # Exclusive x0, y0, x1, y1.


def fit_track_bounds(frame_at: Callable[[int], NDArray[Any]], count: int,
                     track_ids: tuple[int, ...],
                     cancelled: Callable[[], bool] = lambda: False) -> CropBounds | None:
    """Enclose complete masks across time with 5% padding on every side."""
    bounds = None
    height = width = 0
    for frame in range(count):
        if cancelled():
            return None
        labels = frame_at(frame)
        height, width = labels.shape
        rows, columns = np.nonzero(np.isin(labels, track_ids))
        if not len(rows):
            continue
        current = (int(columns.min()), int(rows.min()),
                   int(columns.max()) + 1, int(rows.max()) + 1)
        if bounds is None:
            bounds = current
        else:
            bounds = (min(bounds[0], current[0]), min(bounds[1], current[1]),
                      max(bounds[2], current[2]), max(bounds[3], current[3]))
    if bounds is None:
        raise ValueError("The selected cells have no masks in this channel and Z plane.")
    x0, y0, x1, y1 = bounds
    extra_x, extra_y = ceil((x1 - x0) * 0.05), ceil((y1 - y0) * 0.05)
    return max(0, x0 - extra_x), max(0, y0 - extra_y), min(width, x1 + extra_x), min(height, y1 + extra_y)


def clip_polyline(points: NDArray[np.float64], width: int,
                   height: int) -> list[NDArray[np.float64]]:
    """Clip each segment, retaining crossings whose endpoints are both outside.

    Liang–Barsky clipping uses the entering/leaving fractions of each segment.
    Separate visible pieces remain separate instead of gaining connecting lines.
    """
    pieces: list[list[NDArray[np.float64]]] = []
    for start, end in zip(points[:-1], points[1:], strict=True):
        delta = end - start
        entering, leaving = 0.0, 1.0
        for direction, distance in ((-delta[0], start[0]), (delta[0], width - start[0]),
                                    (-delta[1], start[1]), (delta[1], height - start[1])):
            if direction == 0:
                if distance < 0:
                    leaving = -1
                    break
                continue
            fraction = distance / direction
            if direction < 0:
                entering = max(entering, float(fraction))
            else:
                leaving = min(leaving, float(fraction))
        if entering > leaving:
            continue
        first, last = start + entering * delta, start + leaving * delta
        if pieces and np.allclose(pieces[-1][-1], first, rtol=0, atol=1e-8):
            pieces[-1].append(last)
        else:
            pieces.append([first, last])
    return [np.asarray(piece, dtype=np.float64) for piece in pieces]
