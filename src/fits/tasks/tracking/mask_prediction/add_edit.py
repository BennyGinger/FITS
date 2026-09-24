"""Single-mask prediction for tracking-mask addition and correction."""

from fits.tasks.tracking.mask_prediction.foundation import MaskPredictionFoundation


class AddEditPredictor(MaskPredictionFoundation):
    """Predict one mask from image evidence, prompts, and editing constraints."""

