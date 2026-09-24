"""
Small experiment-trained pixel classifier for local interactive segmentation.
"""
from __future__ import annotations

from math import sqrt
from typing import Sequence

import numpy as np
from scipy.ndimage import (
    binary_closing,
    binary_dilation,
    binary_erosion,
    binary_fill_holes,
    gaussian_filter,)
from skimage.draw import disk
from skimage.morphology import remove_small_holes, remove_small_objects

from fits.tasks.tracking.mask_prediction.classifier import fit_logistic, pixel_features
from fits.tasks.tracking.mask_prediction.geometry import components_at_points, crop_bounds
from fits.tasks.tracking.mask_prediction.evidence import combine_auxiliary_masks, mask_agreement
from fits.tasks.tracking.mask_prediction.types import (
    AddEditProposal, Array, BoolArray, FloatArray, Point)

__all__ = [
    "MaskPredictionFoundation",
    "AddEditProposal",
    "combine_auxiliary_masks",
    "mask_agreement",
]


class MaskPredictionFoundation:
    """Balanced logistic pixel classifier learned from existing experiment masks."""

    def __init__(self, *, maximum_samples_per_class: int = 40_000) -> None:
        self.maximum_samples_per_class = maximum_samples_per_class
        self.feature_mean: FloatArray | None = None
        self.feature_scale: FloatArray | None = None
        self.coefficients: FloatArray | None = None
        self.intercept = 0.0
        self.typical_area = 0.0
        self.typical_diameter = 0.0

    def fit(self, images: Sequence[Array], masks: Sequence[Array]) -> None:
        """
        Fit from matching YX image and label planes.
        """
        if len(images) != len(masks) or not images:
            raise ValueError("Training images and masks must be non-empty and have equal length.")
        feature_parts: list[FloatArray] = []
        class_parts: list[BoolArray] = []
        object_areas: list[int] = []
        rng = np.random.default_rng(0)
        remaining = {False: self.maximum_samples_per_class, True: self.maximum_samples_per_class}

        for image, labels in zip(images, masks, strict=True):
            image_array = np.asarray(image)
            label_array = np.asarray(labels)
            if image_array.ndim != 2 or image_array.shape != label_array.shape:
                raise ValueError("Each training image and mask must be matching YX arrays.")
            foreground = label_array != 0
            
            for object_id in np.unique(label_array[foreground]):
                area = int(np.count_nonzero(label_array == object_id))
                if area:
                    object_areas.append(area)
            confident_foreground = np.asarray(binary_erosion(foreground, iterations=1), dtype=bool)
            confident_background = ~np.asarray(binary_dilation(foreground, iterations=3), dtype=bool)
            features = pixel_features(image_array)
            for class_value, selected in ((True, confident_foreground),
                                          (False, confident_background)):
                indices = np.flatnonzero(selected)
                take = min(len(indices), remaining[class_value])
                if take <= 0:
                    continue
                if take < len(indices):
                    indices = rng.choice(indices, take, replace=False)
                feature_parts.append(features.reshape(-1, features.shape[-1])[indices])
                class_parts.append(np.full(take, class_value, dtype=bool))
                remaining[class_value] -= take

        if not feature_parts or any(remaining[value] == self.maximum_samples_per_class
                                    for value in (False, True)):
            raise ValueError("Existing masks do not provide both foreground and background examples.")
        if not object_areas:
            raise ValueError("No segmented objects are available to estimate cell size.")
        x = np.concatenate(feature_parts)
        y = np.concatenate(class_parts).astype(np.float64)
        feature_mean = np.asarray(np.mean(x, axis=0), dtype=np.float64)
        feature_scale = np.asarray(np.std(x, axis=0), dtype=np.float64)
        feature_scale[feature_scale < 1e-6] = 1.0
        standardized = (x - feature_mean) / feature_scale
        self.feature_mean = feature_mean
        self.feature_scale = feature_scale
        self.coefficients, self.intercept = fit_logistic(standardized, y)
        self.typical_area = float(np.median(object_areas))
        self.typical_diameter = 2.0 * sqrt(self.typical_area / np.pi)

    def fit_from_prompts(self, 
                         image: Array,
                         positive_points: Sequence[Point],
                         negative_points: Sequence[Point],
                         expected_diameter: float
                         ) -> None:
        """
        Bootstrap an empty session from confident click neighbourhoods.
        """
        image_array = np.asarray(image)
        if image_array.ndim != 2 or not positive_points:
            raise ValueError("Cold-start segmentation needs a YX image and a positive point.")
        if expected_diameter < 4:
            raise ValueError("Expected cell diameter must be at least 4 pixels.")
        features = pixel_features(image_array)
        foreground = np.zeros(image_array.shape, dtype=bool)
        background = np.zeros(image_array.shape, dtype=bool)
        seed_radius = max(1, int(round(expected_diameter * 0.08)))
        for point in positive_points:
            rows, columns = disk(point, seed_radius, shape=image_array.shape)
            foreground[rows, columns] = True
        for point in negative_points:
            rows, columns = disk(point, seed_radius * 2, shape=image_array.shape)
            background[rows, columns] = True
        rows, columns = np.ogrid[:image_array.shape[0], :image_array.shape[1]]
        far_from_positive = np.ones(image_array.shape, dtype=bool)
        exclusion_radius2 = (expected_diameter * 0.75) ** 2
        for point_y, point_x in positive_points:
            far_from_positive &= ((rows - point_y) ** 2 + (columns - point_x) ** 2
                                  >= exclusion_radius2)
        background |= far_from_positive
        x = np.concatenate((features[foreground], features[background]))
        y = np.concatenate((np.ones(np.count_nonzero(foreground)),
                            np.zeros(np.count_nonzero(background))))
        if len(x) > self.maximum_samples_per_class * 2:
            rng = np.random.default_rng(0)
            indices = rng.choice(len(x), self.maximum_samples_per_class * 2, replace=False)
            x, y = x[indices], y[indices]
        feature_mean = np.asarray(np.mean(x, axis=0), dtype=np.float64)
        feature_scale = np.asarray(np.std(x, axis=0), dtype=np.float64)
        feature_scale[feature_scale < 1e-6] = 1.0
        standardized = (x - feature_mean) / feature_scale
        self.feature_mean = feature_mean
        self.feature_scale = feature_scale
        self.coefficients, self.intercept = fit_logistic(standardized, y)
        self.typical_diameter = float(expected_diameter)
        self.typical_area = float(np.pi * (expected_diameter / 2.0) ** 2)

    def predict(self,
                image: Array,
                positive_points: Sequence[Point],
                negative_points: Sequence[Point] = (),
                *,
                auxiliary_mask: Array | None = None,
                auxiliary_weight: float = 0.0,
                temporal_mask: Array | None = None,
                temporal_weight: float = 0.0,
                initial_mask: Array | None = None,
                excluded_mask: Array | None = None,
                ) -> AddEditProposal:
        """
        Predict a cell around positive YX points and refine it with negative points.
        """
        if self.coefficients is None or self.feature_mean is None or self.feature_scale is None:
            raise RuntimeError("Fit the local segmentation model before prediction.")
        if not positive_points:
            raise ValueError("At least one positive point is required.")
        image_array = np.asarray(image)
        if image_array.ndim != 2:
            raise ValueError("Local segmentation expects a YX image plane.")
        image_shape = (int(image_array.shape[0]), int(image_array.shape[1]))
        bounds = crop_bounds(
            image_shape, positive_points, self.typical_diameter,
            extent_mask=initial_mask)
        y0, y1, x0, x1 = bounds
        crop = image_array[y0:y1, x0:x1]
        feature_mean = self.feature_mean
        feature_scale = self.feature_scale
        coefficients = self.coefficients
        features = pixel_features(crop)
        standardized = (features - feature_mean) / feature_scale
        logits = standardized @ coefficients + self.intercept
        weight = float(np.clip(auxiliary_weight, 0.0, 1.0))
        if auxiliary_mask is not None and weight > 0:
            auxiliary = np.asarray(auxiliary_mask[y0:y1, x0:x1], dtype=bool)
            # A soft log-odds adjustment supports compatible shapes without copying them.
            logits = logits + weight * np.where(auxiliary, 1.5, -0.15)
        time_weight = float(np.clip(temporal_weight, 0.0, 1.0))
        if temporal_mask is not None and time_weight > 0:
            temporal = np.asarray(temporal_mask[y0:y1, x0:x1], dtype=bool)
            edge_softness = max(0.8, self.typical_diameter * 0.035)
            softened = np.asarray(gaussian_filter(
                temporal.astype(np.float64), edge_softness), dtype=np.float64)
            # Previous shape is strong positive evidence, but absence outside it is
            # only a weak penalty so protrusions and shape changes remain possible.
            logits = logits + time_weight * (3.0 * softened - 0.10)
        if initial_mask is not None:
            initial = np.asarray(initial_mask[y0:y1, x0:x1], dtype=bool)
            if np.any(initial):
                softened = np.asarray(gaussian_filter(
                    initial.astype(np.float64),
                    max(0.6, self.typical_diameter * 0.02)), dtype=np.float64)
                # Preserve the working mask as the starting solution. Click evidence
                # can still overcome this locally, especially for negative prompts.
                logits = logits + 4.0 * softened
                # A positive click inside a drawn border means the border is a
                # strong shape hint. Close small hand-drawn gaps, fill its interior,
                # and strongly favour only the enclosed component containing a click.
                gap = max(1, int(round(self.typical_diameter * 0.04)))
                closed = np.asarray(
                    binary_closing(initial, iterations=gap), dtype=bool)
                enclosed = np.asarray(binary_fill_holes(closed), dtype=bool)
                enclosed = components_at_points(enclosed, positive_points, bounds)
                if np.any(enclosed):
                    logits = logits + np.where(enclosed, 5.0, 0.0)
        radius = max(1.5, self.typical_diameter * 0.10)
        rows, columns = np.ogrid[:crop.shape[0], :crop.shape[1]]
        for point_y, point_x in positive_points:
            distance2 = (rows - (point_y - y0)) ** 2 + (columns - (point_x - x0)) ** 2
            logits += 3.0 * np.exp(-distance2 / (2.0 * radius ** 2))
            logits += 3.5 * self._prompt_feature_similarity(
                standardized, point_y - y0, point_x - x0)
        for point_y, point_x in negative_points:
            distance2 = (rows - (point_y - y0)) ** 2 + (columns - (point_x - x0)) ** 2
            logits -= 6.0 * np.exp(-distance2 / (2.0 * radius ** 2))
            logits -= 5.0 * self._prompt_feature_similarity(
                standardized, point_y - y0, point_x - x0)
        excluded = (None if excluded_mask is None else
                    np.asarray(excluded_mask[y0:y1, x0:x1], dtype=bool))
        if excluded is not None:
            logits[excluded] = -30.0
        probability = 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))
        # A conservative boundary is preferable for correction: positive clicks can
        # grow missed regions, while an oversized first proposal hides neighbours.
        candidate = probability >= 0.70
        candidate = np.asarray(remove_small_objects(
            candidate, max_size=max(3, int(self.typical_area * 0.05) - 1)),
            dtype=bool)
        candidate = np.asarray(remove_small_holes(
            candidate, max_size=max(3, int(self.typical_area * 0.08) - 1)),
            dtype=bool)
        candidate = np.asarray(binary_fill_holes(candidate), dtype=bool)
        candidate = components_at_points(candidate, positive_points, bounds)
        if excluded is not None:
            candidate[excluded] = False
        for point_y, point_x in negative_points:
            local_y, local_x = point_y - y0, point_x - x0
            if 0 <= local_y < candidate.shape[0] and 0 <= local_x < candidate.shape[1]:
                candidate[local_y, local_x] = False
        return AddEditProposal(
            mask=np.asarray(candidate, dtype=bool), bounds=bounds,
            probability=np.asarray(probability, dtype=np.float64),
            auxiliary_weight=weight, temporal_weight=time_weight)

    @staticmethod
    def _prompt_feature_similarity(features: FloatArray,
                                   row: int, column: int) -> FloatArray:
        """Score crop pixels by similarity to a robust neighbourhood around a click."""
        row0, row1 = max(0, row - 1), min(features.shape[0], row + 2)
        col0, col1 = max(0, column - 1), min(features.shape[1], column + 2)
        reference = np.median(features[row0:row1, col0:col1], axis=(0, 1))
        distance = np.mean((features - reference) ** 2, axis=-1)
        return np.asarray(np.exp(-0.5 * np.clip(distance, 0.0, 30.0)),
                          dtype=np.float64)
