from __future__ import annotations

import logging
from typing import cast

from fits_io.client import FitsIO
from progress_bar import pbar

from fits.environment.constant import ExecMode, FitsName, STEP_SEGMENT
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.engines.executors import execute
from fits.workflows.engines.provenance import StepProfile, provenance_payload
from fits.workflows.channels.metadata import build_channel_metadata, labels_to_src_indices, src_indices_to_labels
from fits.workflows.engines.model_cache import segment_model_cache
from fits.workflows.channels.mask_output import merge_step_metadata, prepare_mask_output
from fits.workflows.channels.loading import get_array
from fits.workflows.engines.run_decision import decide_run


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
    if exp_state.image is None:
        failed_state = exp_state.with_error(STEP_SEGMENT, f"ExperimentState for {exp_state.original_image} has no image set; cannot run {step_profile.step_name}.",)
        logger.error("%s failed for %s: missing image input", step_profile.step_name, exp_state.original_image)
        return failed_state

    # NOTE: for ProcessPool execution, pass ExecutionContext explicitly (ContextVar doesn't propagate).
    ctx = get_ctx()
    run_dir = ctx.run_dir

    mask_path = exp_state.workdir / output_name
    chan_seg = list(settings.channel_to_segment)
    chan_nuc = list(settings.nuclear_channel)

    try:
        reader = FitsIO.from_path(exp_state.image)
        requested_seg_src_idxs = labels_to_src_indices(reader, chan_seg)
        run = decide_run(exp_state, step_profile.step_name, settings.overwrite, requested_seg_src_idxs)

        if run.is_complete:
            logger.debug("Skipping %s for %s: all requested channels already covered.", step_profile.step_name, exp_state.original_image)
            return exp_state

        seg_src_chan_idx = cast(list[int], run.missing_items)
        missing_seg_labels = src_indices_to_labels(reader, seg_src_chan_idx)
        requested_channels = list(dict.fromkeys(missing_seg_labels + chan_nuc))
        logger.debug("%s will be executed for channel(s): %s", step_profile.step_name, requested_channels)

        # Get image array and associated axis order
        input_array, input_axis_order = get_array(reader, requested_channels)

        # Initialize model wrapper (with caching)
        model_params = settings.model_dump()
        cp_wrapper = segment_model_cache.get_wrapper(model_params)

        # Run segmentation and the key 'channels': {src_idx: {seg_meta}; as well as the axis order
        masks_array = cp_wrapper.run(input_array, input_axis_order)
        segment_metadata = build_channel_metadata(seg_src_chan_idx, cp_wrapper.segmentation_meta)
        out_axis_order = cp_wrapper.output_axis_order
        if out_axis_order is None:
            raise ValueError("Output axis order from CellposeWrapper is None. Cannot save output without axis order information.")

        # Merge with existing mask if present
        mask_output = prepare_mask_output(reader, mask_path, masks_array, out_axis_order, seg_src_chan_idx)
        save_metadata = merge_step_metadata(mask_path, step_profile.step_name, segment_metadata, mask_output.structural_metadata)
        logger.debug("Mask save payload: shape=%s, axes=%s, labels=%s", mask_output.array.shape, mask_output.axes, mask_output.channel_labels)

        # Save
        fits_payload = provenance_payload(step_profile)
        save_path = reader.save_array(mask_output.array, 
                                      axis_order=mask_output.axes, 
                                      channel_labels=mask_output.channel_labels, 
                                      output_name=output_name, 
                                      user_name=ctx.user_name, 
                                      **fits_payload, 
                                      custom_metadata=save_metadata)
        logger.debug("%s completed for %s", step_profile.step_name, exp_state.workdir_relative(run_dir))

        # Update experiment state
        new_st = exp_state.with_masks(save_path)
        new_st = new_st.with_completed_step(STEP_SEGMENT)
        logger.debug("Produced new ExperimentState: %s", new_st)
        new_st.save()
        return new_st

    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.workdir)
        print(f"[ERROR] Step '{step_profile.step_name}' failed for {exp_state.workdir}: {e}")
        return exp_state.with_error(STEP_SEGMENT, str(e))


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
        

    



