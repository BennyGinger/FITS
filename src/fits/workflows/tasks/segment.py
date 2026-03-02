from collections.abc import Iterator, Sequence
from typing import Any
import logging

from cellpose_kit.client import CellposeWrapper
from fits_io.client import FitsIO
from numpy.typing import NDArray
import numpy as np
from progress_bar.decorator import pbar

from fits.environment.constant import ExecMode, FitsName
from fits.environment.runtime import get_ctx
from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.payload import build_payload, hash_payload
from fits.workflows.provenance import StepProfile


logger = logging.getLogger(__name__)






@pbar(desc="Segment")
def run_segment(settings: SegmentSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: FitsName) -> Iterator[list[ExperimentState]]:
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare input and payload
    payload = build_payload(settings, step_profile, ctx.user_name, output_name)
    settings_hash = hash_payload(payload)
    requested_channels = settings.channel_to_segment
    logger.debug(f"Payload for {step_profile.step_name}: {payload}")
    
    # Prepare the executor
    exec_mode: ExecMode = settings.execution
    workers: int | None = settings.workers
    ordered: bool = settings.ordered_execution
    logger.debug(f"Executing {step_profile.step_name} with mode: {exec_mode} and workers: {workers} in ordered mode: {ordered}")
    
    # Set up worker (per experiment)
    def worker(st: ExperimentState) -> list[ExperimentState]:
        logger.debug("Will be executed with parameters: %s", payload)
        
        # Check if needed
        if not st.needs_run(step_profile.step_name, settings_hash, settings.overwrite, required_output=output_name):
            logger.debug("Skipping %s for %s as it is up to date.", step_profile.step_name, st.original_image)
            return [st]
        
        if st.image is None:
            logger.error("ExperimentState for %s has no image path set. Cannot run %s.", st.original_image, step_profile.step_name)
            return [st]
        
        # Setup CellposeWrapper with settings
        cp_wrapper = CellposeWrapper.from_dict(payload)
        cp_wrapper.setup()
        cp_version = cp_wrapper.version
        if cp_version is None:
            raise ValueError("Cellpose version could not be determined from the model context. Please ensure that the CellposeWrapper is properly set up and can identify the version.")
    
        # Get the array iterators
        reader = FitsIO.from_path(st.image)
        iter_arrays, shapes = _ensure_channel_compatibility(reader, requested_channels, cp_version, cp_wrapper.use_nuclear_channel)
        
        # Run segmentation
        masks = np.zeros_like(shapes[0], dtype=np.uint16)
        
        
        
def _resolve_channels_to_segment(reader: FitsIO, requested: Sequence[str]) -> list[int]:
    """
    Return channel indices to segment.
    
    Parameters:
        reader: FitsIO reader instance for the input image, used to access channel labels and number of channels.
        requested: Sequence of channel labels specified in the settings for segmentation (e.g., ["GFP", "DAPI"]).
    """
    labels = reader.channel_labels
    if labels is None:
        logger.warning("Input image has no channel labels; cannot resolve requested channels by label.")
        return []

    if not requested:
        logger.warning("No channels specified for segmentation; defaulting to all channels.")
        return list(range(len(labels)))
    
    out: list[int] = []
    for item in requested:
        try:
            out.append(labels.index(item))
        except ValueError as e:
            raise ValueError(f"Unknown channel label: {item!r}. Available: {labels}") from e
    return out



def _validate_channels_for_cellpose(cp_version: str, num_channels: int) -> None:
    """Validate that requested channels are compatible with Cellpose version."""
    
    if cp_version == 'v3':
        if num_channels < 2:
            raise ValueError(f"Cellpose v3 with nuclear channel requires >= 2 channels, got {num_channels}.")
    elif cp_version == 'v4':
        if num_channels < 2 or num_channels > 3:
            raise ValueError(f"Cellpose v4 with nuclear channel requires 2-3 channels, got {num_channels}.")
    else:
        raise ValueError(f"Unsupported Cellpose version: {cp_version}. Only 'v3' and 'v4' are supported.")

def _get_array(reader: FitsIO, requested_channels: Sequence[int]) -> NDArray[Any]:
    """
    Get the correct array with the requested channels. It will also 
    
    Parameters:
        array: The input image array to validate.
        cp_version: The version of Cellpose being used (e.g., 'v3', 'v4').
        requested_channels: The list of channel labels requested for segmentation.
        use_nuclear_channel: Whether nuclear channel usage is enabled in settings.
    """
    labels = reader.channel_labels
    if labels is None:
        raise ValueError("Input image has no channel labels; cannot resolve requested channels.")
    
    if len(requested_channels) == len(labels):
        array = reader.get_array()
    else:
        array = reader.get_channel_array(requested_channels)
    
    if isinstance(array, list):
        raise ValueError(f"{StepProfile.step_name} does not support multi-series files.")
    
    return array
    
def _ensure_channel_compatibility(reader: FitsIO, requested_channels: Sequence[str], cp_version: str, use_nuclear_channel: bool) -> tuple[list[Iterator[NDArray[Any]]], list[tuple[int, ...]]]:
    
    resolved_chan = _resolve_channels_to_segment(reader, requested_channels)
    
    array = _get_array(reader, resolved_chan) 
    
    # Get array properties
    axis_order = reader.axes[0]
    channel_axis = reader.axis_index('C')[0]
    if channel_axis is None:
        num_channels = 1
    else:
        num_channels = array.shape[channel_axis]
    
    if not use_nuclear_channel:
        return _iter_frame(array, reader, axis_order, channel_axis, split_channels=True)
    
    _validate_channels_for_cellpose(cp_version, num_channels)
    
    # Pad for v4 if needed
    if cp_version == 'v4' and num_channels == 2:
        array = reader.pad_array(array)
    
    return _iter_frame(array, reader, axis_order, channel_axis, split_channels=False)


def _iter_frame(array: NDArray[Any], reader: FitsIO, axis_order: str, channel_axis: int | None, split_channels: bool,) -> tuple[list[Iterator[NDArray[Any]]], list[tuple[int, ...]]]:
    if not split_channels or channel_axis is None:
        return [reader.iter_frames_from_array(array, axis_order=axis_order)], [array.shape]

    per_channel_axis_order = axis_order.replace('C', '')
    iters: list[Iterator[NDArray[Any]]] = []
    shapes = []
    for idx in range(array.shape[channel_axis]):
        slicer: list[slice | int] = [slice(None)] * array.ndim
        slicer[channel_axis] = idx
        channel_array = array[tuple(slicer)]
        shapes.append(channel_array.shape)
        iters.append(reader.iter_frames_from_array(channel_array, axis_order=per_channel_axis_order))
    return iters, shapes
    
    