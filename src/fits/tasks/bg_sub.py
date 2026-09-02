from __future__ import annotations

import logging

from bg_sub import bg_sub
from fits_io import FitsIO

from fits.environment.state import ExperimentState
from fits.settings.models import BGSubSettings
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import decide_run
from fits.workflows.errors import StepExecutionError


logger = logging.getLogger(__name__)


def remove_bg(settings: BGSubSettings, exp_state: ExperimentState, step_profile: StepProfile) -> list[ExperimentState]:
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
    input_path = exp_state.artifact(step_profile.input_artifact)
    if input_path is None:
        raise StepExecutionError(
            f"Step {step_profile.step_name!r} failed for {exp_state.experiment_id}: "
            f"missing {step_profile.input_artifact!r} input.")
    
    try:
        reader = FitsIO.from_path(input_path)
        run = decide_run(exp_state, step_profile, settings.overwrite)
        if run.is_complete:
            logger.debug("Skipping %s for %s: all requested channels already covered.",
                         step_profile.step_name, 
                         exp_state.experiment_id)
            return [exp_state]
        
        # Select the channels to be processed
        selection = reader.select_included_channels(excluded_labels=settings.exclude_channel)
        
        processed = bg_sub(selection.array,
                           sigma=settings.sigma,
                           size=settings.size,
                           threshold=settings.threshold,
                           statistic=settings.statistic,
                           execution=settings.bg_execution,
                           max_workers=settings.bg_workers,)
        
        corrected_array = selection.rebuild(processed)

        exporter_channel = selection.processed_indices if settings.exclude_channel is not None else 'all'
        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                               created_by=step_profile.distribution,
                                               exported_channel=exporter_channel,
                                               channels_params=settings.to_payload_dict())

        # Save output
        save_path = reader.save_array(corrected_array,
                                      output_name=step_profile.output_name,
                                      export_channels=reader.channel_labels,
                                      artifact_kind=step_profile.output_artifact,
                                      created_by=step_profile.distribution,
                                      custom_metadata=updated_state.metadata_dump,)

        logger.debug("%s completed for %s", step_profile.step_name, exp_state.experiment_id)
        
        # Update and return state
        new_st = updated_state.with_complete_step(step_name=step_profile.step_name,
                                                artifact_kind=step_profile.output_artifact,
                                                artifact_path=save_path,)
        logger.debug("Produced new ExperimentState: %s", new_st)
        new_st.save_state()
        return [new_st]
    
    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        raise StepExecutionError(
            f"Step {step_profile.step_name!r} failed for "
            f"{exp_state.experiment_id}: {e}") from e
