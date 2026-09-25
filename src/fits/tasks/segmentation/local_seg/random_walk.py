"""Crop-local, marker-guided candidate from raw-image contrast."""

from typing import Sequence

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion, binary_fill_holes, gaussian_filter, sobel
from skimage.draw import disk
from skimage.segmentation import random_walker

from fits.tasks.segmentation.local_seg.geometry import components_at_points
from fits.tasks.segmentation.local_seg.types import BoolArray, Bounds, FloatArray, Point


def random_walk_candidate(
    intensity: FloatArray,
    positive_points: Sequence[Point],
    negative_points: Sequence[Point],
    bounds: Bounds,
    diameter: float,
    allowed: BoolArray,
) -> BoolArray | None:
    """Find the clicked cell using intensity transitions, or decline weak evidence."""
    # Sparse random-walker solves become expensive on unusually large crops.
    # The caller retains the original classifier for those cases.
    if allowed.size > 160_000 or not np.any(allowed):
        return None
    y0, _, x0, _ = bounds
    allowed = components_at_points(allowed, positive_points, bounds)
    if not np.any(allowed):
        return None
    smooth = gaussian_filter(intensity, max(0.7, min(1.3, diameter * 0.025)))
    low, high = np.percentile(smooth[allowed], (5, 98))
    if high - low < 1e-6:
        return None
    local = np.clip((smooth - low) / (high - low), 0.0, 1.0)

    markers = np.zeros(intensity.shape, dtype=np.int32)
    markers[~allowed] = -1
    rows, columns = np.ogrid[:intensity.shape[0], :intensity.shape[1]]
    distance2 = np.full(intensity.shape, np.inf)
    for point_y, point_x in positive_points:
        distance2 = np.minimum(
            distance2, (rows - (point_y - y0)) ** 2
            + (columns - (point_x - x0)) ** 2)
    outer = distance2 >= (diameter * 0.85) ** 2
    boundary = allowed & ~binary_erosion(allowed)
    markers[allowed & (outer | boundary)] = 2
    negative_seed = np.zeros(intensity.shape, dtype=bool)
    for point_y, point_x in negative_points:
        row, column = point_y - y0, point_x - x0
        if 0 <= row < markers.shape[0] and 0 <= column < markers.shape[1]:
            rr, cc = disk((row, column), max(2, diameter * 0.10),
                          shape=markers.shape)
            negative_seed[rr, cc] = allowed[rr, cc]
            markers[negative_seed] = 2
    for point_y, point_x in positive_points:
        row, column = point_y - y0, point_x - x0
        if 0 <= row < markers.shape[0] and 0 <= column < markers.shape[1]:
            rr, cc = disk((row, column), max(1, diameter * 0.035),
                          shape=markers.shape)
            markers[rr, cc] = np.where(allowed[rr, cc], 1, markers[rr, cc])
    if not np.any(markers == 1) or not np.any(markers == 2):
        return None

    region = np.asarray(
        random_walker(local, markers, beta=90, mode="cg_j", tol=1e-5) == 1, dtype=bool)
    region = components_at_points(region, positive_points, bounds)
    area = np.count_nonzero(region)
    expected_area = np.pi * (diameter / 2.0) ** 2
    if area < 0.15 * expected_area or area > 3.0 * expected_area:
        return None
    edge = region & ~binary_erosion(region)
    gradient = np.hypot(sobel(local, axis=0), sobel(local, axis=1))
    if not np.any(edge) or np.median(gradient[edge]) < max(
        0.035, 0.65 * np.percentile(gradient[allowed], 70)
    ):
        return None
    # A dark interior usually stops at the inner side of its bright membrane.
    # Include that band, but stop before the adjacent dark background/cell.
    interior_level = float(np.median(local[region]))
    for _ in range(max(1, int(round(diameter * 0.15)))):
        ring = binary_dilation(region) & allowed & ~region
        if not np.any(ring) or np.median(local[ring]) < interior_level + 0.15:
            break
        region |= ring
    region = np.asarray(binary_fill_holes(region), dtype=bool) & allowed
    region[negative_seed] = False
    return region
