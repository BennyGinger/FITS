"""Single-mask prediction for tracking-mask addition and correction."""

from fits.tasks.segmentation.local_seg.foundation import MaskPredictionFoundation


class AddEditPredictor(MaskPredictionFoundation):
    """
    Predict one mask from image evidence, prompts, and editing constraints.
    """
