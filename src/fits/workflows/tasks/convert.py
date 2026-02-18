from collections.abc import Iterator
import logging
from time import sleep

from fits_io.client import FitsIO
from progress_bar import pbar

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx
from fits.environment.constant import FITS_FILES, ExecMode
from fits.workflows.executors import execute
from fits.workflows.payload import build_payload
from fits.workflows.provenance import StepProfile
from fits.settings.models import ConvertSettings


logger = logging.getLogger(__name__)


@pbar(desc="Convert")
def run_convert(settings: ConvertSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: str) -> Iterator[list[ExperimentState]]:
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare input and payload
    payload = build_payload(settings, step_profile, ctx.user_name, output_name)
    payload['expected_filenames'] = FITS_FILES # add expected_filenames to payload for validation in client
    channel_labels = payload.get("channel_labels", None)
    logger.debug(f"Payload for conversion: {payload}")
    
    # Prepare the executor
    exec_mode: ExecMode = settings.execution
    workers: int | None = settings.workers
    ordered: bool = settings.ordered_execution
    logger.debug(f"Executing conversion with mode: {exec_mode} and workers: {workers} in ordered mode: {ordered}")
    
    # Set up worker (per experiment)
    def worker(st: ExperimentState) -> list[ExperimentState]:
        logger.debug("Conversion will be executed with parameters: %s", payload)

        reader = FitsIO.from_path(st.original_image, channel_labels=channel_labels,)
        sleep(2) # simulate some delay in reading the file, to better demonstrate the progress bar

        save_paths = reader.convert_to_fits(**payload)
        logger.info("Conversion completed for %s", st.original_image)
        logger.debug("Saved FITS files at: %s", save_paths)

        return [st.replace(image=p, last_step=step_profile.step_name)
                            for p in save_paths]
    logger.info("Starting conversion with settings: %s", payload)
    return execute(exp_state, worker, mode=exec_mode, workers=workers, ordered=ordered)
    