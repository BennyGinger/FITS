"""Headless micro-SAM backend for interactive Add/Edit prediction."""

from __future__ import annotations

from hashlib import sha1
import logging
from time import perf_counter
from typing import Any, Sequence, cast

import numpy as np

from fits.tasks.segmentation.local_seg.geometry import crop_bounds
from fits.tasks.segmentation.local_seg.types import AddEditProposal, Array, Point, SamPrediction, SamPredictor

logger = logging.getLogger(__name__)
MODEL_TYPE = "vit_t_lm"
DEVICE = "cpu"
class MicroSamPredictor:
    """Lazy, single-crop micro-SAM predictor for interactive editing."""

    def __init__(self) -> None:
        self._predictor: SamPredictor | None = None
        self._embedding_key: tuple[tuple[int, ...], str, str] | None = None
        self._embeddings: Any | None = None
        self._previous_logits: np.ndarray | None = None
        self._prediction_context: object | None = None

    @property
    def is_ready(self) -> bool:
        return self._predictor is not None

    def prepare(self) -> None:
        """Load μSAM so the first prompt only computes its crop embedding."""
        self._get_predictor()

    def _get_predictor(self) -> SamPredictor:
        if self._predictor is None:
            started = perf_counter()
            from micro_sam.util import get_sam_model

            self._predictor = cast(
                SamPredictor,
                get_sam_model(model_type=MODEL_TYPE, device=DEVICE))
            logger.info("micro-SAM model %s loaded on %s in %.3f s",
                        MODEL_TYPE, DEVICE, perf_counter() - started)
        return self._predictor

    @staticmethod
    def _crop_key(crop: np.ndarray) -> tuple[tuple[int, ...], str, str]:
        contiguous = np.ascontiguousarray(crop)
        digest = sha1(contiguous.view(np.uint8)).hexdigest()
        return contiguous.shape, contiguous.dtype.str, digest

    def _get_embeddings(self, crop: np.ndarray) -> tuple[Any, bool]:
        key = self._crop_key(crop)
        if key == self._embedding_key and self._embeddings is not None:
            return self._embeddings, True

        from micro_sam.util import precompute_image_embeddings

        predictor = self._get_predictor()
        started = perf_counter()
        embeddings = precompute_image_embeddings(
            cast(Any, predictor), crop, ndim=2, verbose=False)
        self._embedding_key = key
        self._embeddings = embeddings
        logger.info("micro-SAM prepared crop embedding for shape %s in %.3f s",
                    crop.shape,
                    perf_counter() - started)
        return embeddings, False

    @staticmethod
    def _segment_from_points(predictor: SamPredictor,
                             points_yx: np.ndarray,
                             labels: np.ndarray,
                             embeddings: Any
                             ) -> SamPrediction:
        from micro_sam.prompt_based_segmentation import segment_from_points

        return cast(SamPrediction, segment_from_points(
            cast(Any, predictor), points_yx, labels,
            image_embeddings=embeddings,
            multimask_output=False, return_all=True))

    @staticmethod
    def _segment_from_mask(predictor: SamPredictor,
                           mask: np.ndarray,
                           points_xy: np.ndarray | None,
                           labels: np.ndarray | None,
                           embeddings: Any
                           ) -> SamPrediction:
        from micro_sam.prompt_based_segmentation import segment_from_mask

        return cast(SamPrediction, segment_from_mask(cast(Any, predictor),
                                                     mask,
                                                     image_embeddings=embeddings,
                                                     use_box=True,
                                                     use_mask=True,
                                                     points=points_xy,
                                                     labels=labels,
                                                     multimask_output=False,
                                                     return_all=True))

    @staticmethod
    def _refine_from_logits(predictor: SamPredictor,
                            points_yx: np.ndarray,
                            labels: np.ndarray,
                            embeddings: Any,
                            logits: np.ndarray
                            ) -> SamPrediction:
        from micro_sam.util import set_precomputed

        set_precomputed(cast(Any, predictor), embeddings)
        return predictor.predict(point_coords=points_yx[:, ::-1],
                                 point_labels=labels,
                                 mask_input=logits[None],
                                 multimask_output=False)

    @staticmethod
    def _mask_to_logits(mask: np.ndarray) -> np.ndarray:
        """
        Convert a displayed binary mask to SAM's 256-square logit input.
        """
        import torch
        from segment_anything.utils.transforms import ResizeLongestSide

        binary = np.asarray(mask == 1, dtype=np.float32)
        if binary.shape != (256, 256):
            resized = ResizeLongestSide(256).apply_image_torch(
                torch.from_numpy(binary[None, None]))
            binary = np.asarray(resized.numpy().squeeze(), dtype=np.float32)
            if binary.shape != (256, 256):
                padding = ((0, 256 - binary.shape[0]),
                           (0, 256 - binary.shape[1]))
                binary = np.pad(binary, padding, mode="constant")
        foreground_logit = np.log(0.999 / 0.001)
        return np.asarray(
            np.where(binary > 0.5, foreground_logit, -foreground_logit),
            dtype=np.float32)

    def synchronize_mask(self, mask: Array, prediction_context: object) -> bool:
        """
        Make the next refinement start from the mask displayed by FITS.
        """
        if self._prediction_context != prediction_context:
            return False
        self._previous_logits = self._mask_to_logits(
            np.asarray(mask, dtype=bool))
        logger.info("micro-SAM refinement logits synchronized to displayed mask")
        return True

    def predict(self,
                image: Array,
                positive_points: Sequence[Point],
                negative_points: Sequence[Point] = (),
                *,
                initial_mask: Array | None = None,
                excluded_mask: Array | None = None,
                occupied_mask: Array | None = None,
                expected_diameter: float,
                prediction_context: object | None = None,
                continue_from_previous: bool = False,
                ) -> AddEditProposal:
        """
        Predict a crop-local mask from accumulated global YX prompts.
        """
        if not positive_points and initial_mask is None:
            raise ValueError("A positive point or initial mask is required.")
        image_array = np.asarray(image)
        if image_array.ndim != 2:
            raise ValueError("micro-SAM local segmentation expects a YX image plane.")
        image_shape = (int(image_array.shape[0]), int(image_array.shape[1]))
        if expected_diameter < 4:
            raise ValueError("Expected cell diameter must be at least 4 pixels.")

        # Keep the first-click crop stable so corrective clicks can reuse both
        # its embedding and SAM's previous low-resolution mask logits.
        initial_array = None if initial_mask is None else np.asarray(initial_mask, dtype=bool)
        crop_points = list(positive_points[:1])
        if not crop_points and initial_array is not None and np.any(initial_array):
            coordinates = np.column_stack(np.nonzero(initial_array))
            center = np.round(np.mean(coordinates, axis=0)).astype(int)
            crop_points = [(int(center[0]), int(center[1]))]
        if not crop_points:
            raise ValueError("The initial mask is empty.")
        bounds = crop_bounds(image_shape,
                             crop_points,
                             expected_diameter,
                             extent_mask=initial_mask)
        y0, y1, x0, x1 = bounds
        if any(not (y0 <= y < y1 and x0 <= x < x1)
               for y, x in tuple(positive_points) + tuple(negative_points)):
            bounds = crop_bounds(image_shape,
                                 positive_points,
                                 expected_diameter,
                                 extent_mask=initial_mask)
        y0, y1, x0, x1 = bounds
        crop = np.asarray(image_array[y0:y1, x0:x1])
        embeddings, reused = self._get_embeddings(crop)

        global_points = tuple(positive_points) + tuple(negative_points)
        # micro_sam.segment_from_points accepts YX and reverses it for SAM.
        local_points_yx = np.asarray(
            [(y - y0, x - x0) for y, x in global_points], dtype=np.float64).reshape(-1, 2)
        labels = np.concatenate((np.ones(len(positive_points), dtype=np.uint8),
                                 np.zeros(len(negative_points), dtype=np.uint8),))

        predictor = self._get_predictor()
        started = perf_counter()
        initial = None if initial_mask is None else np.asarray(
            initial_mask[y0:y1, x0:x1], dtype=bool)
        previous_logits = self._previous_logits
        can_refine = (continue_from_previous
                        and reused
                        and previous_logits is not None
                        and self._prediction_context == prediction_context)
        if can_refine:
            assert previous_logits is not None
            masks, scores, logits = self._refine_from_logits(predictor,
                                                             local_points_yx,
                                                             labels,
                                                             embeddings,
                                                             previous_logits)
            used_initial_mask = False
            refinement = "previous logits"
        elif initial is not None and np.any(initial):
            # segment_from_mask passes supplied point coordinates straight to
            # SAM, whose convention is XY rather than FITS' YX.
            points_xy = local_points_yx[:, ::-1] if len(local_points_yx) else None
            point_labels = labels if len(labels) else None
            masks, scores, logits = self._segment_from_mask(
                predictor, initial, points_xy, point_labels, embeddings)
            used_initial_mask = True
            refinement = "binary mask"
        else:
            masks, scores, logits = self._segment_from_points(predictor,
                                                              local_points_yx,
                                                              labels,
                                                              embeddings)
            used_initial_mask = False
            refinement = "points"

        scores_array = np.asarray(scores).reshape(-1)
        logits_array = np.asarray(logits)
        best = int(np.argmax(scores_array)) if len(scores_array) > 1 else 0
        self._previous_logits = np.asarray(logits_array[best], dtype=np.float32)
        self._prediction_context = prediction_context

        candidate = np.asarray(masks[0], dtype=bool).copy()
        occupied = None if occupied_mask is None else np.asarray(occupied_mask[y0:y1, x0:x1], dtype=bool)
        excluded = None if excluded_mask is None else np.asarray(excluded_mask[y0:y1, x0:x1], dtype=bool)
        if occupied is not None:
            candidate[occupied] = False
        if excluded is not None:
            candidate[excluded] = False
        for point_y, point_x in negative_points:
            local_y, local_x = point_y - y0, point_x - x0
            if 0 <= local_y < candidate.shape[0] and 0 <= local_x < candidate.shape[1]:
                candidate[local_y, local_x] = False

        logger.info("micro-SAM prompt prediction (%d positive, %d negative; "
                    "embedding %s; refinement %s; initial mask %s) took %.3f s",
                    len(positive_points), len(negative_points),
                    "reused" if reused else "new", refinement,
                    "used" if used_initial_mask else "unused",
                    perf_counter() - started)
        return AddEditProposal(mask=candidate, bounds=bounds)


# Process-local so the model and active crop embedding survive between clicks.
DEFAULT_MICROSAM_BACKEND = MicroSamPredictor()
