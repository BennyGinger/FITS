"""Shared tracking-mask prediction with dedicated Add/Edit and Split APIs."""

from fits.tasks.tracking.mask_prediction.add_edit import AddEditPredictor
from fits.tasks.tracking.mask_prediction.evidence import (
    combine_auxiliary_masks, mask_agreement)
from fits.tasks.tracking.mask_prediction.foundation import MaskPredictionFoundation
from fits.tasks.tracking.mask_prediction.split import SplitPredictor
from fits.tasks.tracking.mask_prediction.types import AddEditProposal, SplitProposal

__all__ = [
    "AddEditPredictor",
    "AddEditProposal",
    "MaskPredictionFoundation",
    "SplitPredictor",
    "SplitProposal",
    "combine_auxiliary_masks",
    "mask_agreement",
]
