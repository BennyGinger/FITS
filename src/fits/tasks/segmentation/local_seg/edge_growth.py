"""Edge-guided candidate for cells with a dim interior and bright membrane."""

from math import ceil
from typing import Sequence

import numpy as np
from scipy.ndimage import (
    binary_dilation, binary_erosion, binary_fill_holes, gaussian_filter, sobel,
)
from skimage.segmentation import watershed

from fits.tasks.segmentation.local_seg.geometry import components_at_points
from fits.tasks.segmentation.local_seg.types import BoolArray, Bounds, FloatArray, Point


def membrane_edge_candidate(
    intensity: FloatArray,
    positive_points: Sequence[Point],
    negative_points: Sequence[Point],
    bounds: Bounds,
    diameter: float,
    allowed: BoolArray,
) -> BoolArray | None:
    """Grow a clicked interior to an image boundary, or decline weak evidence."""
    y0, _, x0, _ = bounds
    anchor = (positive_points[0][0] - y0, positive_points[0][1] - x0)
    smooth = gaussian_filter(intensity, max(0.8, min(1.5, diameter * 0.035)))
    # The classifier uses frame-wide scaling, but an edge is meaningful
    # relative to contrast in this crop. This also helps dim membranes in
    # frames containing a few much brighter cells.
    low, high = np.percentile(smooth[allowed], (5, 98))
    local = np.clip((smooth - low) / max(high - low, 1e-6), 0.0, 1.0)
    if not _has_bright_membrane(local, anchor, diameter, allowed):
        return None

    gradient = np.hypot(sobel(local, axis=0), sobel(local, axis=1))
    markers = np.zeros(intensity.shape, dtype=np.int32)
    markers[allowed & ~binary_erosion(allowed)] = 2
    for point_y, point_x in negative_points:
        row, column = point_y - y0, point_x - x0
        if 0 <= row < markers.shape[0] and 0 <= column < markers.shape[1]:
            if allowed[row, column]:
                markers[row, column] = 2
    for point_y, point_x in positive_points:
        row, column = point_y - y0, point_x - x0
        if 0 <= row < markers.shape[0] and 0 <= column < markers.shape[1]:
            if allowed[row, column]:
                markers[row, column] = 1
    if not np.any(markers == 1) or not np.any(markers == 2):
        return None

    region = np.asarray(watershed(gradient, markers, mask=allowed) == 1, dtype=bool)
    expected_area = np.pi * (diameter / 2.0) ** 2
    area = np.count_nonzero(region)
    if area < 0.2 * expected_area or area > 3.0 * expected_area:
        return None
    boundary = region & ~binary_erosion(region)
    if not np.any(boundary):
        return None
    if np.median(gradient[boundary]) < max(
        0.03, 0.75 * np.percentile(gradient[allowed], 70)
    ):
        return None

    # Watershed often stops at the inner membrane edge; include its bright band.
    region = np.asarray(binary_dilation(region, iterations=1), dtype=bool) & allowed
    region = np.asarray(binary_fill_holes(region), dtype=bool) & allowed
    return components_at_points(region, positive_points, bounds)


def _has_bright_membrane(
    image: FloatArray,
    anchor: Point,
    diameter: float,
    allowed: BoolArray,
) -> bool:
    """Require a bright band around much of a dim clicked interior."""
    row, column = anchor
    row0, row1 = max(0, row - 1), min(image.shape[0], row + 2)
    col0, col1 = max(0, column - 1), min(image.shape[1], column + 2)
    center = float(np.median(image[row0:row1, col0:col1]))
    rows, columns = np.ogrid[:image.shape[0], :image.shape[1]]
    dy, dx = rows - row, columns - column
    radius = np.hypot(dy, dx)
    annulus = allowed & (radius >= 0.25 * diameter) & (radius <= 1.05 * diameter)
    if np.count_nonzero(annulus) < 16:
        return False
    if np.percentile(image[annulus], 90) < center + 0.06:
        return False

    sectors = (np.arctan2(dy, dx) + np.pi) * (16.0 / (2.0 * np.pi))
    available = 0
    bright = 0
    for sector_index in range(16):
        sector = annulus & (sectors >= sector_index) & (sectors < sector_index + 1)
        if not np.any(sector):
            continue
        available += 1
        if np.percentile(image[sector], 90) >= center + 0.06:
            bright += 1
    return available >= 8 and bright >= max(6, ceil(0.45 * available))
