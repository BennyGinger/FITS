"""Score and combine auxiliary mask evidence."""

from math import sqrt
from typing import Sequence

import numpy as np

from fits.tasks.tracking.mask_prediction.types import Array, BoolArray


def mask_agreement(target_masks: Sequence[Array],
                   auxiliary_masks: Sequence[Array]
                   ) -> float:
    """
    Return a conservative 0..1 reliability score for an auxiliary channel.
    """
    if len(target_masks) != len(auxiliary_masks) or not target_masks:
        return 0.0
    intersections = target_total = auxiliary_total = 0
    for target, auxiliary in zip(target_masks, auxiliary_masks, strict=True):
        target_binary = np.asarray(target) != 0
        auxiliary_binary = np.asarray(auxiliary) != 0
        if target_binary.shape != auxiliary_binary.shape:
            raise ValueError("Mask channels used for agreement must have matching shapes.")
        
        intersections += int(np.count_nonzero(target_binary & auxiliary_binary))
        target_total += int(np.count_nonzero(target_binary))
        auxiliary_total += int(np.count_nonzero(auxiliary_binary))
    
    if target_total == 0 or auxiliary_total == 0:
        return 0.0
    precision = intersections / auxiliary_total
    coverage = intersections / target_total
    return float(sqrt(precision * coverage))


def combine_auxiliary_masks(masks: Sequence[Array],
                            weights: Sequence[float]
                            ) -> tuple[BoolArray | None, float]:
    """
    Combine available priors and return their evidence-weighted confidence.
    """
    usable = [(np.asarray(mask, dtype=bool), float(weight))
              for mask, weight in zip(masks, weights, strict=True)
              if weight > 0]
    if not usable:
        return None, 0.0
    shape = usable[0][0].shape
    votes = np.zeros(shape, dtype=np.float64)
    total = 0.0
    for mask, weight in usable:
        if mask.shape != shape:
            raise ValueError("Auxiliary masks must have matching shapes.")
        votes += mask * weight
        total += weight
    combined = np.asarray(votes >= max(0.25, total * 0.5), dtype=bool)
    confidence = min(1.0, total / len(usable))
    return combined, confidence
