"""Image-guided prediction of two sister regions inside one tracking mask."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import binary_dilation, distance_transform_edt, label
from skimage.segmentation import watershed

from fits.tasks.tracking.mask_prediction.split_geometry import (
    split_mask_automatically)
from fits.tasks.tracking.mask_prediction.types import Array, SplitProposal


class SplitPredictor:
    """Partition a selected mask using image evidence and optional user guidance."""

    def predict(self, mask: Array, *, image: Array | None = None,
                guide: Array | None = None) -> SplitProposal:
        selected = np.asarray(mask, dtype=bool)
        geometric = split_mask_automatically(selected)
        if image is None and guide is None:
            return SplitProposal(
                regions=geometric.regions, gap=np.zeros_like(selected),
                method=geometric.method)

        markers = self._markers_from_regions(geometric.regions, selected)
        distance = np.asarray(distance_transform_edt(selected), dtype=np.float64)
        elevation = -distance.astype(np.float64)
        normalized: NDArray[np.float64] | None = None
        if image is not None:
            values = np.asarray(image, dtype=np.float64)
            if values.shape != selected.shape:
                raise ValueError("Split image and selected mask must have matching shapes.")
            finite = values[selected & np.isfinite(values)]
            if finite.size:
                low, high = np.percentile(finite, (2.0, 98.0))
                scale = max(float(high - low), 1e-9)
                normalized = np.asarray(
                    np.clip((values - low) / scale, 0.0, 1.0),
                    dtype=np.float64)
                # Dark valleys are plausible boundaries between fluorescent cells.
                elevation += 2.0 * (1.0 - normalized)

        constrained_guide = np.zeros_like(selected)
        if guide is not None:
            guide_array = np.asarray(guide, dtype=bool)
            if guide_array.shape != selected.shape:
                raise ValueError("Split guide and selected mask must have matching shapes.")
            constrained_guide = guide_array & selected
            guided_markers = self._markers_from_guide(
                selected, constrained_guide, distance)
            if guided_markers is not None:
                markers = guided_markers
            elevation[constrained_guide] = float(np.max(elevation[selected]) + 10.0)

        regions = np.asarray(
            watershed(elevation, markers=markers, mask=selected), dtype=np.uint8)
        if not np.any(regions == 1) or not np.any(regions == 2):
            regions = geometric.regions
        gap = np.zeros_like(selected)
        if normalized is not None:
            first_side = np.asarray(binary_dilation(regions == 1), dtype=bool)
            second_side = np.asarray(binary_dilation(regions == 2), dtype=bool)
            interface = first_side & second_side & selected
            interface_neighbourhood = np.asarray(
                binary_dilation(interface, iterations=2), dtype=bool) & selected
            selected_values = normalized[selected]
            dark_limit = float(np.percentile(selected_values, 15.0))
            gap = np.asarray(
                interface_neighbourhood & (normalized <= dark_limit), dtype=bool)
            regions[gap] = 0
        return SplitProposal(
            regions=regions, gap=gap,
            method=("guided_image_watershed" if np.any(constrained_guide)
                    else "image_watershed"))

    @staticmethod
    def _markers_from_regions(regions: NDArray[np.uint8],
                              mask: NDArray[np.bool_]) -> NDArray[np.int32]:
        distance = np.asarray(distance_transform_edt(mask), dtype=np.float64)
        markers = np.zeros(mask.shape, dtype=np.int32)
        for marker in (1, 2):
            candidates = regions == marker
            weighted = np.where(candidates, distance, -1.0)
            row, column = np.unravel_index(
                int(np.argmax(weighted)), mask.shape)
            markers[int(row), int(column)] = marker
        return markers

    @staticmethod
    def _markers_from_guide(
            mask: NDArray[np.bool_],
            guide: NDArray[np.bool_],
            distance: NDArray[np.float64],
            ) -> NDArray[np.int32] | None:
        """Put seeds on opposite sides when a stroke crosses the selected mask."""
        components = np.zeros(mask.shape, dtype=np.int32)
        count = label(mask & ~guide, output=components)
        if not isinstance(count, int) or count < 2:
            return None
        sizes = np.bincount(components.ravel())[1:]
        chosen = np.argsort(sizes)[-2:] + 1
        if np.any(sizes[chosen - 1] < max(2, int(np.count_nonzero(mask) * 0.05))):
            return None
        markers = np.zeros(mask.shape, dtype=np.int32)
        for marker, component in enumerate(chosen, start=1):
            weighted = np.where(components == component, distance, -1.0)
            row, column = np.unravel_index(
                int(np.argmax(weighted)), mask.shape)
            markers[int(row), int(column)] = marker
        return markers
