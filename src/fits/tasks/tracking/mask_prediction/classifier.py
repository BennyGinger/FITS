"""Feature extraction and logistic fitting for local segmentation."""

import numpy as np
from scipy.ndimage import gaussian_filter, sobel, uniform_filter

from fits.tasks.tracking.mask_prediction.types import Array, FloatArray


def pixel_features(image: Array) -> FloatArray:
    """
    Build normalized intensity, scale, edge, and texture features.
    """
    values = np.asarray(image, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        normalized = np.zeros_like(values)
    else:
        low, high = np.percentile(finite, (1.0, 99.0))
        scale = high - low
        normalized = (np.zeros_like(values) if scale <= 0 else
                      np.clip((values - low) / scale, 0, 1))
    smooth_small = np.asarray(gaussian_filter(normalized, 1.0), dtype=np.float64)
    smooth_large = np.asarray(gaussian_filter(normalized, 3.0), dtype=np.float64)
    gradient = np.hypot(sobel(smooth_small, axis=0), sobel(smooth_small, axis=1))
    local_mean = np.asarray(uniform_filter(normalized, size=7), dtype=np.float64)
    local_variance = np.maximum(uniform_filter(normalized ** 2, size=7) - local_mean ** 2, 0)
    return np.asarray(np.stack((normalized, 
                                smooth_small, 
                                smooth_large,
                                smooth_small - smooth_large, 
                                gradient,
                                np.sqrt(local_variance)), 
                               axis=-1), 
                      dtype=np.float64)


def fit_logistic(x: FloatArray, y: FloatArray) -> tuple[FloatArray, float]:
    """
    Fit the small balanced logistic classifier used by the interactive tool.
    """
    coefficients = np.zeros(x.shape[1], dtype=np.float64)
    intercept = 0.0
    count_positive = max(1, int(np.count_nonzero(y)))
    count_negative = max(1, len(y) - count_positive)
    sample_weight = np.where(
        y > 0, len(y) / (2 * count_positive),
        len(y) / (2 * count_negative))
    learning_rate = 0.15
    for _ in range(180):
        logits = np.clip(x @ coefficients + intercept, -30.0, 30.0)
        prediction = 1.0 / (1.0 + np.exp(-logits))
        error = (prediction - y) * sample_weight
        coefficients -= learning_rate * (
            (x.T @ error) / len(y) + 0.002 * coefficients)
        intercept -= learning_rate * float(np.mean(error))
    return coefficients, intercept
