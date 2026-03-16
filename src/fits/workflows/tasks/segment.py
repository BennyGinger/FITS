from __future__ import annotations

import logging

from fits_io.client import FitsIO
from progress_bar import pbar

from fits.environment.constant import ExecMode, FitsName, STEP_SEGMENT
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.executors import execute
from fits.workflows.provenance import StepProfile
from fits.workflows.tasks.segment_utils.metadata import build_segment_channel_metadata, resolve_segment_source_channel_indices
from fits.workflows.tasks.segment_utils.model_cache import segment_model_cache
from fits.workflows.tasks.segment_utils.array import get_array
from fits.workflows.tasks.utils import should_skip_step, build_fits_payload


logger = logging.getLogger(__name__)


def segment_one(settings: SegmentSettings, exp_state: ExperimentState, step_profile: StepProfile, output_name: FitsName) -> ExperimentState:
    """
    Process a single experiment through the segment step.

    Args:
        settings: Segment step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
        output_name: Output FITS name scheme

    Returns:
        Single output experiment state.
    """
    if should_skip_step(exp_state, step_profile.step_name, settings.overwrite):
        logger.debug("Skipping %s for %s as it is up to date.", step_profile.step_name, exp_state.original_image)
        return exp_state
    
    # NOTE: for ProcessPool execution, pass ExecutionContext explicitly (ContextVar doesn't propagate).
    ctx = get_ctx()
    run_dir = ctx.run_dir

    # Prepare channels parameters
    chan_seg = list(settings.channel_to_segment)
    chan_nuc = list(settings.nuclear_channel)
    requested_channels = list(dict.fromkeys(chan_seg + chan_nuc))

    logger.debug("%s will be executed for channel(s): %s", step_profile.step_name, requested_channels)

    if exp_state.image is None:
        failed_state = exp_state.with_error(STEP_SEGMENT, f"ExperimentState for {exp_state.original_image} has no image set; cannot run {step_profile.step_name}.",)
        logger.error("%s failed for %s: missing image input", step_profile.step_name, exp_state.original_image)
        return failed_state

    try:
        reader = FitsIO.from_path(exp_state.image)
        input_array, input_axis_order = get_array(reader, requested_channels)

        # Initialize model wrapper (with caching)
        model_params = settings.model_dump()
        cp_wrapper = segment_model_cache.get_wrapper(model_params)
        
        # Run segmentation
        masks_array = cp_wrapper.run(input_array, input_axis_order)
        
        # Build segmentation metadata with stable source channel identity.
        seg_src_chan_idx = resolve_segment_source_channel_indices(reader, chan_seg)
        segment_metadata = build_segment_channel_metadata(seg_src_chan_idx, cp_wrapper.segmentation_meta)

        # Build FITS metadata for provenance
        fits_payload = build_fits_payload(step_profile, user_name=ctx.user_name, output_name=output_name)
        
        # Extract axis order of the output masks.
        out_axis_order = cp_wrapper.output_axis_order
        if out_axis_order is None:
            raise ValueError("Output axis order from CellposeWrapper is None. Cannot save output without axis order information.")

        # Save
        save_path = reader.save_array(masks_array, axis_order=out_axis_order, channel_labels=chan_seg, **fits_payload, custom_metadata=segment_metadata)
        logger.debug("%s completed for %s", step_profile.step_name, exp_state.workdir_relative(run_dir))

        # Update experiment state
        new_st = exp_state.with_masks(save_path)
        new_st = new_st.with_completed_step(STEP_SEGMENT)
        logger.debug("Produced new ExperimentState: %s", new_st)
        new_st.save()
        return new_st
    
    except Exception as exc:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.workdir)
        return exp_state.with_error(STEP_SEGMENT, str(exc))


def run_segment(settings: SegmentSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: FitsName) -> list[ExperimentState]:
    """
    Batch runner for segment step. Maps segment_one across experiments.

    Args:
        settings: Segment step settings
        exp_state: List of experiment states to process
        step_profile: Step metadata
        output_name: Output FITS name scheme

    Returns:
        Flattened output experiment states for all completed input experiments.
    """
    ctx = get_ctx()

    exec_mode: ExecMode = settings.execution
    workers: int | None = settings.workers
    ordered: bool = settings.ordered_execution
    logger.debug(f"Executing {step_profile.step_name} with mode: {exec_mode} and workers: {workers} in ordered mode: {ordered}")

    def worker(st: ExperimentState) -> list[ExperimentState]:
        with use_ctx(ctx):  # Ensure the execution context is available in worker
            return [segment_one(settings, st, step_profile, output_name)]

    out: list[ExperimentState] = []
    with pbar(total=len(exp_state), desc="Segment", logs="buffered") as pb:
        for produced_states in execute(exp_state, worker, mode=exec_mode, workers=workers, ordered=ordered):
            out.extend(produced_states)
            pb.advance()

    return out
        

    



