from __future__ import annotations

import logging

from bg_sub import bg_sub
from fits_io.client import FitsIO
from progress_bar import pbar

import fits.environment.constant as cst
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.state import ExperimentState
from fits.settings.models import BGSubSettings
from fits.workflows.arrays.converter import flatten_to_frames
from fits.workflows.arrays.loading import get_array
from fits.workflows.engines.executors import execute
from fits.workflows.metadata.provenance import StepProfile
from fits.workflows.metadata.builder import build_step_project_metadata
from fits.workflows.metadata.loading import load_project_metadata_from_reader
from fits.workflows.engines.run_decision import decide_run


logger = logging.getLogger(__name__)


def bg_sub_one(settings: BGSubSettings, exp_state: ExperimentState, step_profile: StepProfile, output_name: cst.FitsName) -> ExperimentState:
    """
    Process a single experiment through the background substraction step.

    Args:
        settings: bg_sub step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
        output_name: Output FITS name scheme

    Returns:
        Single output experiment state.
    """
    if exp_state.image is None:
        failed_state = exp_state.with_error(cst.STEP_BG_SUB, f"ExperimentState for {exp_state.original_image} has no image set; cannot run {step_profile.step_name}.",)
        logger.error("%s failed for %s: missing image input", step_profile.step_name, exp_state.original_image)
        return failed_state
    
    ctx = get_ctx()
    run_dir = ctx.run_dir
    
    try:
        reader = FitsIO.from_path(exp_state.image)
        run = decide_run(exp_state, step_profile.step_name, settings.overwrite)
        
        if run.is_complete:
            logger.debug("Skipping %s for %s: all requested channels already covered.", step_profile.step_name, exp_state.original_image)
            return exp_state
        
        # Get image array and associated axis order
        input_array, input_axis_order = get_array(reader)
        
        # Flatten to list of 2D arrays for processing
        batch = flatten_to_frames(input_array, input_axis_order)
        
        # Run background subtraction
        corrected_batch = bg_sub(batch.frames, sigma=settings.sigma, size=settings.size, threshold=settings.threshold, statistic=settings.statistic)
        
        # Reshape back to original dimensions
        corrected_array = batch.rebuild(list(corrected_batch))

        step_metadata = {
            "sigma": settings.sigma,
            "size": settings.size,
            "threshold": settings.threshold,
            "statistic": settings.serialize_statistic_name(),
        }
        existing_project_metadata = load_project_metadata_from_reader(reader)
        project_metadata = build_step_project_metadata(
            existing_project_metadata=existing_project_metadata,
            step_profile=step_profile,
            user_name=ctx.user_name,
            step_metadata=step_metadata,
            channel_metadata=None,
        )
        
        # Save output
        reader.save_array(
            corrected_array,
            axis_order=input_axis_order,
            channel_labels=reader.channel_labels,
            output_name=output_name,
            project_metadata=project_metadata,
        )
        logger.debug("%s completed for %s", step_profile.step_name, exp_state.workdir_relative(run_dir))
        
        # Update and return state
        new_st = exp_state.with_completed_step(cst.STEP_BG_SUB)
        logger.debug("Produced new ExperimentState: %s", new_st)
        new_st.save()
        return new_st
    
    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.workdir)
        print(f"[ERROR] Step '{step_profile.step_name}' failed for {exp_state.workdir}: {e}")
        return exp_state.with_error(cst.STEP_BG_SUB, str(e))

def run_bg_sub(settings: BGSubSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: cst.FitsName) -> list[ExperimentState]:
    """
    Batch runner for background substration step. Maps bg_sub_one across experiments.

    Args:
        settings: bg_sub step settings
        exp_state: List of experiment states to process
        step_profile: Step metadata
        output_name: Output FITS name scheme

    Returns:
        Flattened output experiment states for all completed input experiments.
    """
    ctx = get_ctx()

    exec_mode: cst.ExecMode = settings.execution
    workers: int | None = settings.workers
    ordered: bool = settings.ordered_execution
    logger.debug(f"Executing {step_profile.step_name} with mode: {exec_mode} and workers: {workers} in ordered mode: {ordered}")

    def worker(st: ExperimentState) -> list[ExperimentState]:
        with use_ctx(ctx):  # Ensure the execution context is available in worker
            return [bg_sub_one(settings, st, step_profile, output_name)]

    out: list[ExperimentState] = []
    with pbar(total=len(exp_state), desc=step_profile.step_name.capitalize(), logs="buffered") as pb:
        for produced_states in execute(exp_state, worker, mode=exec_mode, workers=workers, ordered=ordered):
            out.extend(produced_states)
            pb.advance()

    return out