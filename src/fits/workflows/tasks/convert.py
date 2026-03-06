from collections.abc import Iterator
import logging

from fits_io.client import FitsIO
from progress_bar import pbar

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.constant import ExecMode, FitsName
from fits.workflows.executors import execute
from fits.workflows.payload import build_fits_payload, hash_payload
from fits.workflows.provenance import StepProfile
from fits.settings.models import ConvertSettings
from fits.workflows.tasks.metadata import OutputStateMeta


logger = logging.getLogger(__name__)


def convert_one(settings: ConvertSettings, exp_state: ExperimentState, step_profile: StepProfile, output_name: FitsName) -> list[ExperimentState]:
    """
    Process a single experiment through the convert step.
    
    Args:
        settings: Convert step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
        output_name: Output FITS name scheme
        
    Returns:
        List of output experiment states. Single-series returns one state,
        multi-series returns multiple states (one per series).
    """
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare payload
    payload = build_fits_payload(
        step_profile, 
        **settings.model_dump(), 
        user_name=ctx.user_name,
        output_name=output_name
    )
    z_proj = settings.z_projection
    settings_hash = hash_payload(payload)
    channel_labels = payload.get("channel_labels", None)
    
    logger.debug("Will be executed with parameters: %s", payload)

    reader = FitsIO.from_path(exp_state.original_image, channel_labels=channel_labels)
    current_labels = reader.channel_labels
    
    # Check if needed
    if not exp_state.needs_run(
        step_profile.step_name, 
        settings_hash, 
        current_labels,
        settings.overwrite, 
        output_name
    ):
        logger.debug(
            "Skipping %s for %s as it is up to date.", 
            step_profile.step_name, 
            exp_state.original_image
        )
        return [exp_state]
    
    save_paths = reader.convert_to_fits(**payload)
    
    logger.info("%s completed for %s", step_profile.step_name, exp_state.original_image)
    logger.debug("Saved FITS files at: %s", save_paths)

    out_states: list[ExperimentState] = []
    for i, path in enumerate(save_paths):
        axes = reader.axes[i]
        if z_proj is not None:
            axes = axes.replace('Z', '')  # Remove Z axis if z-projection is applied
        out_meta = OutputStateMeta(
            step=step_profile.step_name,
            axes=axes,
            channel_labels=current_labels,
            hashed_settings=settings_hash,
            with_image=path,
            mark_done=True,
        )
        new_st = exp_state.with_update(out_meta)
        out_states.append(new_st)
    
    for out_st in out_states:
        logger.debug("Produced new ExperimentState: %s", out_st)
        out_st.to_json()
    
    return out_states


@pbar(desc="Convert")
def run_convert(settings: ConvertSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: FitsName) -> Iterator[list[ExperimentState]]:
    """
    Batch runner for convert step. Maps convert_one across experiments.
    
    Args:
        settings: Convert step settings
        exp_state: List of experiment states to process
        step_profile: Step metadata
        output_name: Output FITS name scheme
        
    Yields:
        List of output experiment states for each completed input experiment.
        Each list may contain multiple states for multi-series data.
    """
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare payload for logging
    payload = build_fits_payload(
        step_profile, 
        **settings.model_dump(), 
        user_name=ctx.user_name,
        output_name=output_name
    )
    
    logger.debug(f"Payload for {step_profile.step_name}: {payload}")
    logger.info("Starting %s with settings: %s", step_profile.step_name, payload)
    
    # Prepare the executor
    exec_mode: ExecMode = settings.execution
    workers: int | None = settings.workers
    ordered: bool = settings.ordered_execution
    logger.debug(
        f"Executing {step_profile.step_name} with mode: {exec_mode} "
        f"and workers: {workers} in ordered mode: {ordered}"
    )
    
    # Execute convert_one for each experiment
    def worker(st: ExperimentState) -> list[ExperimentState]:
        with use_ctx(ctx):  # Ensure the execution context is available in worker
            return convert_one(settings, st, step_profile, output_name)
    
    return execute(exp_state, worker, mode=exec_mode, workers=workers, ordered=ordered)
    