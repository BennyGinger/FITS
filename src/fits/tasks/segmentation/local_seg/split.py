"""Unified image-, guidance-, and geometry-informed mask splitting."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import binary_dilation, distance_transform_edt, label
from skimage.morphology import disk, erosion
from skimage.segmentation import watershed

from fits.tasks.segmentation.local_seg.types import Array, SplitProposal


class SplitPredictor:
    """
    Partition a selected mask using image evidence and optional user guidance.
    """

    def predict(self, 
                mask: Array, 
                *, 
                image: Array | None = None,
                supporting_images: Sequence[Array] = (),
                guide: Array | None = None
                ) -> SplitProposal:
        """
        Predict a split of the selected mask using image evidence and optional user guidance.
        """
        selected = np.asarray(mask, dtype=bool)
        area = int(np.count_nonzero(selected))
        if area < 2:
            raise ValueError("The selected mask is too small to split.")
        distance = np.asarray(distance_transform_edt(selected), dtype=np.float64)
        markers = self._geometry_markers(selected, distance, area)
        elevation = -distance.astype(np.float64)
        normalized: NDArray[np.float64] | None = None
        if image is not None:
            normalized = self._combined_intensity(
                image, supporting_images, selected)
            if normalized is not None:
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
        gap = np.zeros_like(selected)
        if normalized is not None:
            first_side = np.asarray(binary_dilation(regions == 1), dtype=bool)
            second_side = np.asarray(binary_dilation(regions == 2), dtype=bool)
            interface = first_side & second_side & selected
            interface_neighbourhood = np.asarray(binary_dilation(interface, iterations=2),
                                                 dtype=bool) & selected
            selected_values = normalized[selected]
            dark_limit = float(np.percentile(selected_values, 15.0))
            gap = np.asarray(interface_neighbourhood & (normalized <= dark_limit), dtype=bool)
            regions[gap] = 0
        return SplitProposal(regions=regions, gap=gap)

    @classmethod
    def _combined_intensity(cls, 
                            image: Array, 
                            supporting_images: Sequence[Array],
                            mask: NDArray[np.bool_]
                            ) -> NDArray[np.float64] | None:
        """
        Combine the active plane with weak cross-channel and temporal evidence.
        """
        primary = cls._normalize_image(image, mask)
        if primary is None:
            return None
        supporting = [normalized for candidate in supporting_images
                      if (normalized := cls._normalize_image(candidate, mask)) is not None]
        if not supporting:
            return primary
        consensus = np.median(np.stack(supporting), axis=0)
        return np.asarray(0.75 * primary + 0.25 * consensus, dtype=np.float64)

    @staticmethod
    def _normalize_image(image: Array, mask: NDArray[np.bool_]) -> NDArray[np.float64] | None:
        """
        Normalize the image within the given mask to the range [0, 1].
        Returns None if the masked region contains no finite values.
        """
        values = np.asarray(image, dtype=np.float64)
        if values.shape != mask.shape:
            raise ValueError("Split images and selected mask must have matching shapes.")
        finite = values[mask & np.isfinite(values)]
        if not finite.size:
            return None
        low, high = np.percentile(finite, (2.0, 98.0))
        scale = max(float(high - low), 1e-9)
        return np.asarray(
            np.clip((values - low) / scale, 0.0, 1.0), dtype=np.float64)

    @classmethod
    def _geometry_markers(cls, 
                          mask: NDArray[np.bool_], 
                          distance: NDArray[np.float64],
                          area: int
                          ) -> NDArray[np.int32]:
        """
        Derive two stable seeds from the selected mask's geometry.
        """
        components, count = cls._connected_components(mask)
        markers = cls._component_markers(components, count, distance, area)
        if markers is not None:
            return markers
        maximum_radius = max(1, min(20, int(np.max(distance))))
        for radius in range(1, maximum_radius + 1):
            eroded = np.asarray(erosion(mask, disk(radius)), dtype=bool)
            components, count = cls._connected_components(eroded)
            markers = cls._component_markers(
                components, count, distance, area)
            if markers is not None:
                return markers
        return cls._balanced_markers(mask, distance)

    @staticmethod
    def _connected_components(mask: NDArray[np.bool_]) -> tuple[NDArray[np.int32], int]:
        """
        Compute connected components for the given binary mask.
        Returns a tuple containing the labeled components array and the number of components.
        """
        components = np.zeros(mask.shape, dtype=np.int32)
        count = label(mask, output=components)
        return components, int(count) if isinstance(count, int) else 0

    @staticmethod
    def _component_markers(components: NDArray[np.int32], 
                           count: int,
                           distance: NDArray[np.float64], 
                           area: int,
                           ) -> NDArray[np.int32] | None:
        """
        Determine markers for the connected components based on their size and distance map.
        Returns None if suitable markers cannot be found.
        """
        if count < 2:
            return None
        sizes = np.bincount(components.ravel())[1:]
        order = np.argsort(sizes)[::-1]
        minimum_size = max(3, int(round(area * 0.03)))
        if (len(order) > 2 and sizes[order[2]] >= minimum_size
                or np.any(sizes[order[:2]] < minimum_size)):
            return None
        markers = np.zeros(components.shape, dtype=np.int32)
        for marker, component in enumerate(order[:2] + 1, start=1):
            weighted = np.where(components == component, distance, -1.0)
            row, column = np.unravel_index(
                int(np.argmax(weighted)), weighted.shape)
            markers[int(row), int(column)] = marker
        return markers

    @staticmethod
    def _balanced_markers(mask: NDArray[np.bool_], 
                          distance: NDArray[np.float64]
                          ) -> NDArray[np.int32]:
        """
        Generate balanced markers for the given mask based on the distance map.
        The markers are placed on opposite sides of the mask along its principal axis.
        """
        coordinates = np.column_stack(np.nonzero(mask)).astype(float)
        centered = coordinates - coordinates.mean(axis=0)
        if len(coordinates) == 2:
            axis = centered[1] - centered[0]
        else:
            _, _, directions = np.linalg.svd(centered, full_matrices=False)
            axis = directions[0]
        projection = centered @ axis
        midpoint = float(np.median(projection))
        markers = np.zeros(mask.shape, dtype=np.int32)
        for marker, half in enumerate(
                (projection <= midpoint, projection > midpoint), start=1):
            candidates = coordinates[half].astype(int)
            if not len(candidates):
                candidates = coordinates.astype(int)
            values = distance[candidates[:, 0], candidates[:, 1]]
            row, column = candidates[int(np.argmax(values))]
            markers[int(row), int(column)] = marker
        return markers

    @staticmethod
    def _markers_from_guide(mask: NDArray[np.bool_],
                            guide: NDArray[np.bool_],
                            distance: NDArray[np.float64],
                            ) -> NDArray[np.int32] | None:
        """
        Put seeds on opposite sides when a stroke crosses the selected mask.
        """
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
