"""Geometry-only fallback for splitting merged tracking masks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import distance_transform_edt, label as connected_components
from skimage.morphology import disk, erosion
from skimage.segmentation import watershed


@dataclass(frozen=True)
class AutomaticSplit:
    """Two proposed regions and the method used to find their markers."""

    regions: NDArray[np.uint8]
    method: str


def split_mask_automatically(mask: NDArray[np.bool_]) -> AutomaticSplit:
    """Split one binary object at a detected neck or with balanced markers."""
    selected = np.asarray(mask, dtype=bool)
    area = int(np.count_nonzero(selected))
    if area < 2:
        raise ValueError("The selected mask is too small to split.")
    distance = np.asarray(distance_transform_edt(selected), dtype=np.float64)

    components, count = _connected_components(selected)
    markers = _meaningful_component_markers(components, count, distance, area)
    method = "disconnected_components"
    if markers is None:
        method = "detected_neck"
        maximum_radius = max(1, min(20, int(np.max(distance))))
        for radius in range(1, maximum_radius + 1):
            eroded = erosion(selected, disk(radius))
            components, count = _connected_components(eroded)
            markers = _meaningful_component_markers(
                components, count, distance, area)
            if markers is not None:
                break
    if markers is None:
        markers = _balanced_markers(selected, distance)
        method = "balanced_watershed"

    regions = np.asarray(
        watershed(-distance, markers=markers, mask=selected), dtype=np.uint8)
    if set(np.unique(regions)) - {0, 1, 2} or not np.any(regions == 1) or not np.any(regions == 2):
        raise ValueError("Could not find two valid regions in the selected mask.")
    return AutomaticSplit(regions=regions, method=method)


def _connected_components(mask: NDArray[np.bool_]) -> tuple[NDArray[np.int32], int]:
    components = np.zeros(mask.shape, dtype=np.int32)
    count = cast(int, connected_components(mask, output=components))
    return components, count


def _meaningful_component_markers(components: NDArray[np.int32],
                                  count: int,
                                  distance: NDArray[np.float64],
                                  original_area: int,
                                  ) -> NDArray[np.int32] | None:
    if count < 2:
        return None
    sizes = np.bincount(components.ravel())[1:]
    order = np.argsort(sizes)[::-1]
    minimum_size = max(3, int(round(original_area * 0.03)))
    if len(order) > 2 and sizes[order[2]] >= minimum_size:
        return None
    chosen = order[:2] + 1
    if np.any(sizes[order[:2]] < minimum_size):
        return None
    markers = np.zeros(components.shape, dtype=np.int32)
    for marker, component in enumerate(chosen, start=1):
        region = components == component
        weighted = np.where(region, distance, -1)
        row, column = np.unravel_index(
            int(np.argmax(weighted)), weighted.shape)
        markers[int(row), int(column)] = marker
    return markers


def _balanced_markers(mask: NDArray[np.bool_],
                      distance: NDArray[np.float64],
                      ) -> NDArray[np.int32]:
    coordinates = np.column_stack(np.nonzero(mask)).astype(float)
    centered = coordinates - coordinates.mean(axis=0)
    if len(coordinates) == 2:
        axis = centered[1] - centered[0]
    else:
        _, _, directions = np.linalg.svd(centered, full_matrices=False)
        axis = directions[0]
    projection = centered @ axis
    midpoint = float(np.median(projection))
    halves = (projection <= midpoint, projection > midpoint)
    markers = np.zeros(mask.shape, dtype=np.int32)
    for marker, half in enumerate(halves, start=1):
        candidates = coordinates[half].astype(int)
        if not len(candidates):
            candidates = coordinates.astype(int)
        values = distance[candidates[:, 0], candidates[:, 1]]
        row, column = candidates[int(np.argmax(values))]
        markers[row, column] = marker
    if np.count_nonzero(markers) != 2:
        first = tuple(coordinates[int(np.argmin(projection))].astype(int))
        second = tuple(coordinates[int(np.argmax(projection))].astype(int))
        markers.fill(0)
        markers[int(first[0]), int(first[1])] = 1
        markers[int(second[0]), int(second[1])] = 2
    return markers
