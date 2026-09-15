import logging
from typing import Any

import numpy as np
from cellpose_kit.client import CellposeWrapper
from fits_io.client import FitsIO
from fits_io.writers.models import ChannelMergeResult

from fits.settings.models import SegmentChannelSettings, SegmentSettings
from fits.tasks.common.channel_results import append_channel_result
from fits.workflows.definitions.models import StepProfile


logger = logging.getLogger(__name__)


def resolve_pending_entries(settings: SegmentSettings,
                            requested_indices: list[int],
                            pending_indices: list[int],
                            ) -> list[tuple[SegmentChannelSettings, int]]:
    """
    Pair configured channels with the indices that still need processing.
    """
    pending = set(pending_indices)
    return [(channel_settings, channel_index)
            for channel_settings, channel_index in zip(
                settings.channels, requested_indices, strict=True)
            if channel_index in pending]


def segment_channels(reader: FitsIO,
                    pending_entries: list[tuple[SegmentChannelSettings, int]],
                    threading: bool,
                    step_profile: StepProfile,
                    ) -> ChannelMergeResult | None:
    """
    Segment all pending channels and combine their results in memory.
    """
    results = None
    for channel_settings, channel_index in pending_entries:
        masks, output_axes = _segment_channel(reader,
                                            channel_settings,
                                            threading,
                                            step_profile,)
        results = append_channel_result(results,
                                        masks,
                                        output_axes,
                                        channel_index,
                                        reader.axes,)
    return results


def _segment_channel(reader: FitsIO,
                    channel_settings: SegmentChannelSettings,
                    threading: bool,
                    step_profile: StepProfile,
                    ) -> tuple[np.ndarray, str]:
    """
    Prepare and segment one configured target channel.
    """
    input_labels = _resolve_input_labels(channel_settings)
    input_results = reader.get_channel(input_labels)
    logger.debug("%s will segment target channel '%s' using input channel(s): %s",
                step_profile.step_name,
                channel_settings.channel,
                input_labels,)
    return _run_model(input_results, channel_settings, threading)


def _resolve_input_labels(channel_settings: SegmentChannelSettings) -> list[str]:
    """
    Resolve the target and optional nuclear input channels.
    """
    input_labels = [channel_settings.channel]
    nuclear_channel = channel_settings.nuclear_channel
    if nuclear_channel is None:
        return input_labels

    if nuclear_channel == channel_settings.channel:
        logger.warning("Nuclear channel '%s' is also the segmentation target; "
                        "it will be supplied only once.",
                        channel_settings.channel,)
    else:
        input_labels.append(nuclear_channel)
    return input_labels


def _run_model(input_results: Any,
            channel_settings: SegmentChannelSettings,
            threading: bool,
            ) -> tuple[np.ndarray, str]:
    """
    Initialize and run Cellpose for one channel.
    """
    try:
        cp_settings = channel_settings.cellpose_payload(threading=threading)
        cp_wrapper = CellposeWrapper.from_dict(cp_settings)
        cp_wrapper.setup()
        masks = cp_wrapper.run(input_results.array, input_results.axes)
        output_axes = cp_wrapper.output_axis_order
        if output_axes is None:
            raise ValueError("Segment model wrapper did not provide an output axis order.")
        return masks, output_axes
    except Exception as exc:
        raise RuntimeError(f"Segmentation failed for channel {channel_settings.channel!r}: {exc}") from exc
