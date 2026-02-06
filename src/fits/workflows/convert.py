import logging

from fits_io.client import FitsIO

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx
from fits.workflows.payload import build_payload
from fits.workflows.provenance import StepProfile
from fits.settings.models import ConvertSettings


logger = logging.getLogger(__name__)

def run_convert(settings: ConvertSettings, exp_state: ExperimentState, step_profile: StepProfile, output_name: str) -> ExperimentState:
    # Get the current execution context
    ctx = get_ctx()
    
    # Prepare input and payload
    payload = build_payload(settings, step_profile, ctx.user_name, output_name)
    logger.debug(f"Payload for conversion: {payload}")
    
    # Initialize reader
    reader = FitsIO.from_path(exp_state.image)
    
    # Run conversion
    save_dirs = reader.convert_to_fits(**payload)
    logger.info(f"Conversion completed for {exp_state.image} at {save_dirs}")
    
    # Update state with new step
    new_exp_state = exp_state.replace(last_step=step_profile.step_name)
    return new_exp_state


    
    