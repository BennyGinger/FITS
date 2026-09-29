"""Local segmentation backends for tracking-mask editing."""

from fits.tasks.segmentation.local_seg.manual import fill_enclosed_mask
from fits.tasks.segmentation.local_seg.microsam import (
    DEFAULT_MICROSAM_BACKEND,
    MicroSamPredictor,
)
from fits.tasks.segmentation.local_seg.split import SplitPredictor
from fits.tasks.segmentation.local_seg.types import (
    AddEditBackend,
    AddEditProposal,
    SplitProposal,
)

__all__ = [
    "AddEditBackend",
    "AddEditProposal",
    "DEFAULT_MICROSAM_BACKEND",
    "MicroSamPredictor",
    "SplitPredictor",
    "SplitProposal",
    "fill_enclosed_mask",
]
