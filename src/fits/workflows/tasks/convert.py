import logging

from fits_io.client import FitsIO

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx
from fits.environment.constant import FITS_FILES
from fits.workflows.payload import build_payload
from fits.workflows.provenance import StepProfile
from fits.settings.models import ConvertSettings


logger = logging.getLogger(__name__)

def run_convert(settings: ConvertSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: str) -> list[ExperimentState]:
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare input and payload
    payload = build_payload(settings, step_profile, ctx.user_name, output_name)
    payload['expected_filenames'] = FITS_FILES # add expected_filenames to payload for validation in client
    channel_labels = payload.get("channel_labels", None)
    logger.debug(f"Payload for conversion: {payload}")
    
    out: list[ExperimentState] = []
    for st in exp_state:
        logger.info(f"Starting conversion for {st.original_image} with settings: {settings}")
    
        # Initialize reader, channel labels are passed to reader for potential use in channel selection during conversion
        reader = FitsIO.from_path(st.original_image, channel_labels=channel_labels)
    
        # Run conversion
        save_paths = reader.convert_to_fits(**payload)
        logger.info(f"Conversion completed for {st.original_image} at {save_paths}")
        
        # Update state with new step
        out.extend([st.replace(image=p,
                              last_step=step_profile.step_name) for p in save_paths])
        
    return out

    
    