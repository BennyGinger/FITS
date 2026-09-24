"""Crop and connected-component helpers for local segmentation."""

from math import ceil
from typing import Sequence

import numpy as np
from scipy.ndimage import label

from fits.tasks.tracking.mask_prediction.types import (
    Array, BoolArray, Bounds, Point)


def crop_bounds(shape: tuple[int, int], 
                points: Sequence[Point],
                diameter: float, 
                *, 
                extent_mask: Array | None = None
                ) -> Bounds:
    """
    Return a bounded crop around prompts and an optional working mask.
    """
    half_size = max(16, int(ceil(diameter * 1.5)))
    center_y = int(round(np.mean([point[0] for point in points])))
    center_x = int(round(np.mean([point[1] for point in points])))
    y0, y1 = max(0, center_y - half_size), min(shape[0], center_y + half_size + 1)
    x0, x1 = max(0, center_x - half_size), min(shape[1], center_x + half_size + 1)
    if extent_mask is not None:
        coordinates = np.column_stack(np.nonzero(extent_mask))
        if coordinates.size:
            margin = max(2, int(round(diameter * 0.1)))
            y0 = max(0, min(y0, int(np.min(coordinates[:, 0])) - margin))
            y1 = min(shape[0], max(y1, int(np.max(coordinates[:, 0])) + margin + 1))
            x0 = max(0, min(x0, int(np.min(coordinates[:, 1])) - margin))
            x1 = min(shape[1], max(x1, int(np.max(coordinates[:, 1])) + margin + 1))
    return y0, y1, x0, x1


def components_at_points(mask: BoolArray, 
                         points: Sequence[Point],
                         bounds: Bounds
                         ) -> BoolArray:
    """
    Keep only foreground components containing positive prompts.
    """
    components = np.zeros(mask.shape, dtype=np.int32)
    label(mask, output=components)
    y0, _, x0, _ = bounds
    selected_ids: set[int] = set()
    for point_y, point_x in points:
        local_y, local_x = point_y - y0, point_x - x0
        if 0 <= local_y < mask.shape[0] and 0 <= local_x < mask.shape[1]:
            component = int(components[local_y, local_x])
            if component:
                selected_ids.add(component)
    if not selected_ids:
        return np.zeros_like(mask, dtype=bool)
    selected = np.zeros(mask.shape, dtype=bool)
    for component_id in selected_ids:
        selected |= components == component_id
    return selected
