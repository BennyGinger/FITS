from collections.abc import Iterator, Sequence
from typing import Any
import logging

from cellpose_kit.client import CellposeWrapper
from fits_io.client import FitsIO
from numpy.typing import NDArray
from progress_bar.decorator import pbar

from fits.environment.constant import ExecMode, FitsName
from fits.environment.runtime import get_ctx
from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.executors import execute
from fits.workflows.payload import build_fits_payload, hash_payload
from fits.workflows.provenance import StepProfile
from fits.workflows.tasks.metadata import OutputStateMeta
from fits.workflows.tasks.utils import get_array


logger = logging.getLogger(__name__)

@pbar(desc="Segment")
def run_segment(settings: SegmentSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: FitsName) -> Iterator[list[ExperimentState]]:
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare input and payload
    fits_payload = build_fits_payload(step_profile, 
                            user_name=ctx.user_name,
                            output_name=output_name,)
    cp_payload = settings.model_dump()
    payload = {**fits_payload, **cp_payload}
    settings_hash = hash_payload(payload)
    chan_seg = list(settings.channel_to_segment)
    chan_nuc = list(settings.nuclear_channel)
    requested_channels = chan_seg + chan_nuc
    logger.debug(f"Payload for {step_profile.step_name}: {payload}")
    logger.debug(f"Requested channels for segmentation: {requested_channels}, with nuclear channels: {chan_nuc}")
    
    # Set up worker (per experiment)
    def worker(st: ExperimentState) -> list[ExperimentState]:
        logger.debug("Will be executed with parameters: %s", payload)
        
        # Check if needed
        if not st.needs_run(step_profile.step_name, 
                            settings_hash, 
                            requested_channels,
                            settings.overwrite, 
                            output_name):
            logger.debug("Skipping %s for %s as it is up to date.", step_profile.step_name, st.original_image)
            return [st]
        
        if st.image is None:
            logger.error("ExperimentState for %s has no image path set. Cannot run %s.", st.original_image, step_profile.step_name)
            return [st]
        
        # Get the array
        reader = FitsIO.from_path(st.image)
        input_array, input_axis_order = get_array(reader, requested_channels)
        
        # Run CellposeWrapper with settings
        cp_wrapper = CellposeWrapper.from_dict(cp_payload)
        cp_wrapper.setup()
        masks_array = cp_wrapper.run(input_array, input_axis_order)
        
        # Save the masks array as a new FITS file
        out_axis_order = cp_wrapper.output_axis_order
        if out_axis_order is None:
            raise ValueError("Output axis order from CellposeWrapper is None. Cannot save output without axis order information.")
        save_path = reader.save_array(masks_array,
                                      axis_order=out_axis_order,
                                      channel_labels=chan_seg,
                                      **fits_payload,
                                      custom_metadata=cp_wrapper.segmentation_meta)
        logger.info("%s completed for %s", step_profile.step_name, st.workdir)
        
        out_meta = OutputStateMeta(step=step_profile.step_name,
                                  axes=reader.axes[0],
                                  channel_labels=chan_seg,
                                  hashed_settings=settings_hash,
                                  with_masks=save_path,
                                  mark_done=True,)
        
        out_states = [st.with_update(out_meta)]
        
        for out_st in out_states:
            logger.debug("Produced new ExperimentState: %s", out_st)
            out_st.to_json()
        return out_states
        
    # Prepare the executor
    exec_mode: ExecMode = settings.execution
    workers: int | None = settings.workers
    ordered: bool = settings.ordered_execution
    logger.debug(f"Executing {step_profile.step_name} with mode: {exec_mode} and workers: {workers} in ordered mode: {ordered}")
    
    logger.info("Starting %s with settings: %s", step_profile.step_name, payload)
    return execute(exp_state, worker, mode=exec_mode, workers=workers, ordered=ordered)
        

    



