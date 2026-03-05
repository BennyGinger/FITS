from collections.abc import Iterator
import logging

from fits_io.client import FitsIO
from progress_bar import pbar

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx
from fits.environment.constant import ExecMode, FitsName
from fits.workflows.executors import execute
from fits.workflows.payload import build_fits_payload, hash_payload
from fits.workflows.provenance import StepProfile
from fits.settings.models import ConvertSettings
from fits.workflows.tasks.metadata import OutputStateMeta


logger = logging.getLogger(__name__)


@pbar(desc="Convert")
def run_convert(settings: ConvertSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: FitsName) -> Iterator[list[ExperimentState]]:
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare input and payload
    payload = build_fits_payload(step_profile, 
                                 **settings.model_dump(), 
                                 user_name=ctx.user_name,
                                 output_name=output_name)
    z_proj = settings.z_projection
    settings_hash = hash_payload(payload)
    channel_labels = payload.get("channel_labels", None)
    logger.debug(f"Payload for {step_profile.step_name}: {payload}")
    
    # Set up worker (per experiment)
    def worker(st: ExperimentState) -> list[ExperimentState]:
        logger.debug("Will be executed with parameters: %s", payload)

        reader = FitsIO.from_path(st.original_image, channel_labels=channel_labels,)
        current_labels = reader.channel_labels
        
        # Check if needed
        if not st.needs_run(step_profile.step_name, 
                            settings_hash, 
                            current_labels,
                            settings.overwrite, 
                            output_name):
            logger.debug("Skipping %s for %s as it is up to date.", step_profile.step_name, st.original_image)
            return [st]
        
        save_paths = reader.convert_to_fits(**payload)
        
        logger.info("%s completed for %s", step_profile.step_name, st.original_image)
        logger.debug("Saved FITS files at: %s", save_paths)

        out_states: list[ExperimentState] = []
        for i, path in enumerate(save_paths):
            axes = reader.axes[i]
            if z_proj is not None:
                axes = axes.replace('Z', '')  # Remove Z axis if z-projection is applied
            out_meta = OutputStateMeta(step=step_profile.step_name,
                                  axes=axes,
                                  channel_labels=current_labels,
                                  hashed_settings=settings_hash,
                                  with_image=path,
                                  mark_done=True,)
            new_st = st.with_update(out_meta)
            out_states.append(new_st)
        
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
    