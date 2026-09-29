"""Local segmentation backends for tracking-mask editing."""

from fits.tasks.segmentation.local_seg.manual import (
    component_at_point,
    fill_clicked_enclosure,
    fill_enclosed_mask,
    remove_clicked_component,
)
from fits.tasks.segmentation.local_seg.microsam import (
    DEFAULT_MICROSAM_BACKEND,
    MicroSamPredictor,
)
from fits.tasks.segmentation.local_seg.split import SplitPredictor
from fits.tasks.segmentation.local_seg.types import (
    AddEditBackend,
    AddEditProposal,
    SamPrediction,
    SamPredictor,
    SplitProposal,
)

__all__ = [
    "AddEditBackend",
    "AddEditProposal",
    "DEFAULT_MICROSAM_BACKEND",
    "MicroSamPredictor",
    "SamPrediction",
    "SamPredictor",
    "SplitPredictor",
    "SplitProposal",
    "component_at_point",
    "fill_clicked_enclosure",
    "fill_enclosed_mask",
    "remove_clicked_component",
]
