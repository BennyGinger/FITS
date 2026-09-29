"""Deterministic helpers for manual tracking-mask edits."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.ndimage import binary_closing, binary_fill_holes, label

from fits.tasks.segmentation.local_seg.geometry import components_at_points, crop_bounds
from fits.tasks.segmentation.local_seg.types import AddEditProposal, Array, Point


def component_at_point(mask: Array, point: Point) -> np.ndarray:
    """Return the connected foreground component containing the point."""
    working = np.asarray(mask, dtype=bool)
    components = np.zeros(working.shape, dtype=np.int32)
    label(working, output=components)
    point_y, point_x = point
    component = int(components[point_y, point_x])
    return components == component if component else np.zeros_like(working)


def fill_clicked_enclosure(mask: Array, point: Point) -> np.ndarray | None:
    """Fill the enclosed background region containing the point."""
    working = np.asarray(mask, dtype=bool)
    holes = np.asarray(binary_fill_holes(working), dtype=bool) & ~working
    components = np.zeros(working.shape, dtype=np.int32)
    label(holes, output=components)
    point_y, point_x = point
    component = int(components[point_y, point_x])
    if component == 0:
        return None
    return working | (components == component)


def remove_clicked_component(mask: Array, point: Point) -> np.ndarray | None:
    """Remove a clicked foreground component when the mask is disconnected."""
    working = np.asarray(mask, dtype=bool)
    components = np.zeros(working.shape, dtype=np.int32)
    label(working, output=components)
    count = int(np.max(components))
    selected = component_at_point(working, point)
    if count < 2 or not np.any(selected):
        return None
    result = working.copy()
    result[selected] = False
    return result


def fill_enclosed_mask(mask: Array,
                        positive_points: Sequence[Point],
                        *,
                        expected_diameter: float,
                        occupied_mask: Array | None = None,
                        excluded_mask: Array | None = None,
                        ) -> AddEditProposal:
    """
    Fill a hand-drawn enclosure containing a positive point.
    """
    working = np.asarray(mask, dtype=bool)
    if working.ndim != 2 or not np.any(working):
        raise ValueError("A non-empty YX manual mask is required.")
    if not positive_points:
        raise ValueError("Click inside the area to fill.")

    height, width = working.shape
    bounds = crop_bounds((height, width),
                         positive_points,
                         expected_diameter,
                         extent_mask=working)
    y0, y1, x0, x1 = bounds
    crop = working[y0:y1, x0:x1]
    filled = np.asarray(binary_fill_holes(crop), dtype=bool)
    selected = components_at_points(filled, positive_points, bounds)
    if not np.any(selected):
        gap = max(1, int(round(expected_diameter * 0.08)))
        closed = np.asarray(binary_closing(crop, iterations=gap), dtype=bool)
        selected = components_at_points(
            np.asarray(binary_fill_holes(closed), dtype=bool),
            positive_points, bounds)

    candidate = crop | selected
    if occupied_mask is not None:
        candidate &= ~np.asarray(occupied_mask[y0:y1, x0:x1], dtype=bool)
    if excluded_mask is not None:
        candidate &= ~np.asarray(excluded_mask[y0:y1, x0:x1], dtype=bool)
    return AddEditProposal(mask=np.asarray(candidate, dtype=bool), bounds=bounds)
