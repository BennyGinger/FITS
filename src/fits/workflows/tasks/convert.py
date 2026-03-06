from collections.abc import Iterator
import logging
from dataclasses import replace

from fits_io.client import FitsIO
from progress_bar import pbar

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.constant import ExecMode, FitsName, STEP_CONVERT
from fits.workflows.executors import execute
from fits.workflows.payload import build_fits_payload
from fits.workflows.provenance import StepProfile
from fits.settings.models import ConvertSettings


logger = logging.getLogger(__name__)


def build_payload(
    settings: ConvertSettings,
    step_profile: StepProfile,
    user_name: str,
    output_name: FitsName,
) -> dict:
    """Compatibility wrapper used by tests and runtime payload wiring."""
    return build_fits_payload(
        step_profile,
        **settings.model_dump(),
        user_name=user_name,
        output_name=output_name,
    )


def _should_skip_convert(exp_state: ExperimentState, step_name: str, overwrite: bool) -> bool:
    """Task-local skip predicate for convert until orchestration-level policy is refactored."""
    if overwrite:
        return False
    return (
        step_name in exp_state.completed_steps
        and exp_state.image is not None
        and exp_state.image.exists()
    )


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
    payload = build_payload(
        settings,
        step_profile,
        user_name=ctx.user_name,
        output_name=output_name,
    )
    channel_labels = payload.get("channel_labels", None)
    
    logger.debug("Will be executed with parameters: %s", payload)

    if _should_skip_convert(exp_state, step_profile.step_name, settings.overwrite):
        logger.debug(
            "Skipping %s for %s as it is up to date.", 
            step_profile.step_name, 
            exp_state.original_image
        )
        return [exp_state]

    try:
        reader = FitsIO.from_path(exp_state.original_image, channel_labels=channel_labels)
        save_paths = reader.convert_to_fits(**payload)

        logger.info("%s completed for %s", step_profile.step_name, exp_state.original_image)
        logger.debug("Saved FITS files at: %s", save_paths)

        out_states: list[ExperimentState] = []
        for path in save_paths:
            branch_state = (
                ExperimentState.init(run_dir=exp_state.run_dir, original_image=exp_state.original_image)
                .with_image(path)
                .with_completed_step(STEP_CONVERT)
            )
            # Convert establishes the canonical image artifact for a branch.
            branch_state = replace(branch_state, masks_rel=None)
            out_states.append(branch_state)

        for out_st in out_states:
            logger.debug("Produced new ExperimentState: %s", out_st)
            out_st.save()

        return out_states
    except Exception as exc:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.original_image)
        failed_state = (
            ExperimentState.init(run_dir=exp_state.run_dir, original_image=exp_state.original_image)
            .with_error(STEP_CONVERT, str(exc))
        )
        return [failed_state]


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
    payload = build_payload(
        settings,
        step_profile,
        user_name=ctx.user_name,
        output_name=output_name,
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
    