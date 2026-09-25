"""Shared array types and results for local segmentation predictions."""

from dataclasses import dataclass
from typing import Any, TypeAlias

import numpy as np
from numpy.typing import NDArray

Array: TypeAlias = NDArray[Any]
FloatArray: TypeAlias = NDArray[np.float64]
BoolArray: TypeAlias = NDArray[np.bool_]
Point: TypeAlias = tuple[int, int]
Bounds: TypeAlias = tuple[int, int, int, int]


@dataclass(frozen=True)
class AddEditProposal:
    """One crop-local prediction and the information needed to place it."""

    mask: BoolArray
    bounds: Bounds
    probability: FloatArray
    auxiliary_weight: float
    temporal_weight: float


@dataclass(frozen=True)
class SplitProposal:
    """Two predicted sister regions and any image-supported gap between them."""

    regions: NDArray[np.uint8]
    gap: BoolArray
