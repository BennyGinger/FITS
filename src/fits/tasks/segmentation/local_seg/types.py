"""Shared array types and results for local segmentation predictions."""

from dataclasses import dataclass
from typing import Any, Protocol, Sequence, TypeAlias

import numpy as np
from numpy.typing import NDArray

Array: TypeAlias = NDArray[Any]
BoolArray: TypeAlias = NDArray[np.bool_]
Point: TypeAlias = tuple[int, int]
Bounds: TypeAlias = tuple[int, int, int, int]
SamPrediction: TypeAlias = tuple[
    NDArray[np.bool_],
    NDArray[np.floating[Any]],
    NDArray[np.floating[Any]],
]


class SamPredictor(Protocol):
    """SAM predictor surface shared by Segment Anything and MobileSAM."""

    def predict(
            self,
            *,
            point_coords: NDArray[Any] | None,
            point_labels: NDArray[Any] | None,
            mask_input: NDArray[Any] | None = None,
            multimask_output: bool = True,
            ) -> SamPrediction:
        ...


@dataclass(frozen=True)
class AddEditProposal:
    """One crop-local mask and the information needed to place it."""

    mask: BoolArray
    bounds: Bounds


class AddEditBackend(Protocol):
    """Backend contract used by the interactive Add/Edit workflow."""

    @property
    def is_ready(self) -> bool:
        """Return whether the model has already been loaded."""
        ...

    def prepare(self) -> None:
        """Load the model without running a prediction."""
        ...

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
        """Return a crop-local prediction for the supplied prompts."""
        ...

    def synchronize_mask(self, mask: Array, prediction_context: object) -> bool:
        """Use FITS' displayed mask as the next refinement state."""
        ...


@dataclass(frozen=True)
class SplitProposal:
    """Two predicted sister regions and any image-supported gap between them."""

    regions: NDArray[np.uint8]
    gap: BoolArray
