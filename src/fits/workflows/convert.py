import logging

from fits_io.client import FitsIO
from progress_bar import pbar

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.constant import ExecMode, FitsName, STEP_CONVERT
from fits.workflows.engines.executors import execute
from fits.workflows.engines.provenance import StepProfile, provenance_payload
from fits.settings.models import ConvertSettings
from fits.workflows.engines.run_decision import decide_run

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
    run = decide_run(exp_state, step_profile.step_name, settings.overwrite)
    
    if run.is_complete:
        logger.debug("Skipping %s for %s as it is up to date.", step_profile.step_name, exp_state.original_image)
        return [exp_state]

    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare payload
    payload = provenance_payload(step_profile, **settings.model_dump(), user_name=ctx.user_name, output_name=output_name,)
    channel_labels = payload.get("channel_labels", None)
    
    logger.debug("%s will be executed with parameters: %s", step_profile.step_name, payload)

    try:
        reader = FitsIO.from_path(exp_state.original_image, channel_labels=channel_labels)
        save_paths = reader.convert_to_fits(**payload)

        logger.debug("%s completed for %s", step_profile.step_name, exp_state.original_image)
        logger.debug("Saved FITS files at: %s", save_paths)

        out_states: list[ExperimentState] = []
        for path in save_paths:
            branch_state = ExperimentState.init(workdir=path.parent, original_image=exp_state.original_image)
            branch_state = branch_state.with_image(path)
            branch_state = branch_state.with_completed_step(STEP_CONVERT)
            out_states.append(branch_state)

        for out_st in out_states:
            logger.debug("Produced new ExperimentState: %s", out_st)
            out_st.save()

        return out_states
    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.original_image)
        print(f"[ERROR] Step '{step_profile.step_name}' failed for {exp_state.original_image}: {e}")
        failed_state = ExperimentState.init(workdir=exp_state.workdir, original_image=exp_state.original_image)
        return [failed_state.with_error(STEP_CONVERT, str(e))]


def run_convert(settings: ConvertSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: FitsName) -> list[ExperimentState]:
    """
    Batch runner for convert step. Maps convert_one across experiments.
    
    Args:
        settings: Convert step settings
        exp_state: List of experiment states to process
        step_profile: Step metadata
        output_name: Output FITS name scheme
        
    Returns:
        Flattened output experiment states for all completed input experiments.
    """
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare the executor
    exec_mode: ExecMode = settings.execution
    workers: int | None = settings.workers
    ordered: bool = settings.ordered_execution
    logger.debug(f"Executing {step_profile.step_name} with mode: {exec_mode} and workers: {workers} in ordered mode: {ordered}")
    
    # Execute convert_one for each experiment
    def worker(st: ExperimentState) -> list[ExperimentState]:
        with use_ctx(ctx):  # Ensure the execution context is available in worker
            return convert_one(settings, st, step_profile, output_name)
    
    out: list[ExperimentState] = []
    with pbar(total=len(exp_state), desc="Convert", logs="buffered") as pb:
        for produced_states in execute(exp_state, worker, mode=exec_mode, workers=workers, ordered=ordered):
            out.extend(produced_states)
            pb.advance()

    return out
    