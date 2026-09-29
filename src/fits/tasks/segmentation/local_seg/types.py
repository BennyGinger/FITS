"""Shared array types and results for local segmentation predictions."""

from dataclasses import dataclass
from typing import Any, Protocol, Sequence, TypeAlias

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


class AddEditBackend(Protocol):
    """Backend contract used by the interactive Add/Edit workflow."""

    def predict(
            self,
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
            auxiliary_weight: float = 0.0,
            temporal_weight: float = 0.0,
            ) -> AddEditProposal:
        """Return a crop-local prediction for the supplied prompts."""
        ...

    def synchronize_mask(
            self, mask: Array, prediction_context: object) -> bool:
        """Use FITS' displayed mask as the next refinement state."""
        ...


@dataclass(frozen=True)
class SplitProposal:
    """Two predicted sister regions and any image-supported gap between them."""

    regions: NDArray[np.uint8]
    gap: BoolArray
