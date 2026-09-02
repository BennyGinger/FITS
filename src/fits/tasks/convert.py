from __future__ import annotations

import logging

from fits_io import FitsIO

from fits.environment.state import ExperimentState
from fits.environment.constant import ARTI_IMG, StepName
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import decide_run
from fits.workflows.errors import StepExecutionError
from fits.settings.models import ConvertSettings

logger = logging.getLogger(__name__)
STEP_CONVERT = StepName.CONVERT


def convert(settings: ConvertSettings, exp_state: ExperimentState, step_profile: StepProfile) -> list[ExperimentState]:
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
    run = decide_run(exp_state, step_profile, settings.overwrite)
    
    if run.is_complete:
        logger.debug("Skipping %s for %s as it is up to date.", 
                     step_profile.step_name, 
                     exp_state.original_image)
        return [exp_state]

    # Run the conversion step
    logger.debug("%s will be executed with settings: %s", step_profile.step_name, settings.model_dump())
    try:
        source = FitsIO.from_path(exp_state.original_image)
        
        selection = source.resolve_channel_selection(channel_labels=settings.channel_labels,
                                                     export_channels=settings.export_channels)
        
        series_readers = source.split_series()
        
        pending_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                               created_by=step_profile.distribution,)
        
        out_states: list[ExperimentState] = []
        for reader in series_readers:
            output = reader.prepare_conversion(selection=selection,
                                               output_name=step_profile.output_name,
                                               artifact_kind=step_profile.output_artifact,
                                               created_by=step_profile.distribution,
                                               custom_metadata=pending_state.metadata_dump,
                                               z_projection=settings.z_projection,)
            
            path = reader.save_array(array=output.array,
                                     metadata=output.metadata,
                                     output_path=output.output_path,
                                     compression=settings.compression,)
            
            branch_state = pending_state.with_complete_step(
                step_name=step_profile.step_name,
                artifact_kind=ARTI_IMG,
                artifact_path=path,
                workdir=path.parent,)
            
            branch_state.save_state()
            out_states.append(branch_state)
            
            logger.debug(
                "Produced converted branch %s from %s.",
                branch_state.experiment_id,
                exp_state.original_image,)
        
        logger.debug("%s completed for %s with %d output series.",
                     step_profile.step_name,
                     exp_state.original_image,
                     len(out_states),)
        return out_states
    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.original_image)
        raise StepExecutionError(
            f"Step {step_profile.step_name!r} failed for "
            f"{exp_state.original_image}: {e}") from e
