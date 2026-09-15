import logging
from typing import Any

import numpy as np
from fits_io.client import FitsIO
from fits_io.writers.models import ChannelMergeResult
from tracklink.api import TrackModel

from fits.workflows.experiments import ExperimentState
from fits.settings.models import TrackPostprocessSettings
from fits.tasks.common.channel_results import append_channel_result
from fits.tasks.tracking.static_masks import process_static_masks
from fits.workflows.definitions.models import StepProfile
from fits.workflows.runtime.errors import StepExecutionError


logger = logging.getLogger(__name__)


def track_channels(tracker: TrackModel,
                   postprocess_settings: TrackPostprocessSettings,
                   mask_reader: FitsIO,
                   image_reader: FitsIO,
                   channel_indices: list[int],
                   channel_labels: list[str],
                   step_profile: StepProfile,
                   exp_state: ExperimentState,
                   ) -> ChannelMergeResult | None:
    """
    Track all pending channels and combine their results in memory.
    """
    results = None
    for channel_index, channel_label in zip(channel_indices,
                                            channel_labels,
                                            strict=True):
        try:
            tracked_mask, output_axes = _track_channel(tracker,
                                                       postprocess_settings,
                                                       mask_reader,
                                                       image_reader,
                                                       channel_label,)
            results = append_channel_result(results,
                                            tracked_mask,
                                            output_axes,
                                            channel_index,
                                            mask_reader.axes,)
        except Exception as exc:
            raise StepExecutionError(f"Step '{step_profile.step_name}' failed for {exp_state.experiment_id}, "
                                    f"channel {channel_label!r}: {exc}"
                                    ) from exc
    return results


def _track_channel(tracker: TrackModel,
                   postprocess_settings: TrackPostprocessSettings,
                   mask_reader: FitsIO,
                   image_reader: FitsIO,
                   channel_label: str,
                   ) -> tuple[np.ndarray, str]:
    """
    Track one channel and return it in the mask's original axis order.
    """
    input_mask = mask_reader.get_channel(channel_label)
    input_image = image_reader.get_channel(channel_label)
    image_array, mask_array, tracking_axes = _prepare_channel_arrays(input_image, input_mask)

    logger.debug("Tracking channel '%s': shape=%s, axes=%s",
                 channel_label,
                 mask_array.shape,
                 tracking_axes,)
    
    tracked_mask = tracker.track(image_array, mask_array)
    if postprocess_settings.enabled:
        tracked_mask = process_static_masks(tracked_mask,
                        shape_similarity=postprocess_settings.shape_similarity,
                        minimum_appearances=postprocess_settings.minimum_appearances,
                        extrapolate_start=postprocess_settings.extrapolate_start,
                        extrapolate_end=postprocess_settings.extrapolate_end,)
    if tracked_mask.shape != mask_array.shape:
        raise ValueError("Tracker output shape does not match its input mask.")

    tracked_mask = np.transpose(tracked_mask,
                                [tracking_axes.index(axis) for axis in input_mask.axes],)
    return tracked_mask, input_mask.axes


def _prepare_channel_arrays(input_image: Any,
                            input_mask: Any,
                            ) -> tuple[np.ndarray, np.ndarray, str]:
    """
    Validate and transpose one image/mask pair for the tracking backend.
    """
    tracking_axes = "TZYX" if "Z" in input_mask.axes else "TYX"
    if (set(input_mask.axes) != set(tracking_axes)
            or set(input_image.axes) != set(tracking_axes)):
        raise ValueError(f"Tracking requires a single-channel time series ({tracking_axes}); "
            f"image axes={input_image.axes}, mask axes={input_mask.axes}.")

    mask_array = np.transpose(input_mask.array,
                            [input_mask.axes.index(axis) for axis in tracking_axes],)
    image_array = np.transpose(input_image.array,
                            [input_image.axes.index(axis) for axis in tracking_axes],)
    if image_array.shape != mask_array.shape:
        raise ValueError(f"Image shape {image_array.shape} does not match mask shape "
                        f"{mask_array.shape}.")
    return image_array, mask_array, tracking_axes
