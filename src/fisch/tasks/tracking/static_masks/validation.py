"""Input validation for static tracked-mask processing."""

import logging
from typing import cast

import numpy as np
from numpy.typing import NDArray


logger = logging.getLogger(__name__)


def validate_masks(masks: NDArray[np.generic]) -> None:
    """
    Validate the shape, dtype, and labels of a tracked-mask movie.
    """
    if not isinstance(masks, np.ndarray):
        logger.error("Static track processing requires a NumPy array.")
        raise TypeError("masks must be a NumPy array.")
    
    if masks.ndim != 3:
        logger.error("Expected a TYX mask movie, received shape %s.", masks.shape)
        raise ValueError(f"masks must have TYX dimensions; got shape {masks.shape}.")
    
    if 0 in masks.shape:
        logger.error("Static track processing received an empty dimension.")
        raise ValueError("masks cannot contain an empty dimension.")
    
    if not np.issubdtype(masks.dtype, np.integer) or masks.dtype == np.bool_:
        logger.error("Tracked masks require an integer dtype; received %s.", masks.dtype)
        raise TypeError(f"masks must use an integer dtype; got {masks.dtype}.")
    
    integer_masks = cast(NDArray[np.integer], masks)
    if np.any(integer_masks < 0):
        logger.error("Tracked masks contain negative labels.")
        raise ValueError("masks cannot contain negative labels.")


def validate_parameters(*, shape_similarity: float, minimum_appearances: int,) -> None:
    """
    Validate thresholds that control static-mask filtering.
    """
    if not 0 <= shape_similarity <= 1:
        raise ValueError("shape_similarity must be between 0 and 1.")
    if minimum_appearances < 1:
        raise ValueError("minimum_appearances must be at least 1.")
