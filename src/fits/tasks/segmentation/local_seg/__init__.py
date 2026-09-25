"""Shared local segmentation with dedicated Add/Edit and Split APIs."""

from fits.tasks.segmentation.local_seg.add_edit import AddEditPredictor
from fits.tasks.segmentation.local_seg.evidence import combine_auxiliary_masks, mask_agreement
from fits.tasks.segmentation.local_seg.foundation import MaskPredictionFoundation
from fits.tasks.segmentation.local_seg.split import SplitPredictor
from fits.tasks.segmentation.local_seg.types import AddEditProposal, SplitProposal

__all__ = [
    "AddEditPredictor",
    "AddEditProposal",
    "MaskPredictionFoundation",
    "SplitPredictor",
    "SplitProposal",
    "combine_auxiliary_masks",
    "mask_agreement",
]
