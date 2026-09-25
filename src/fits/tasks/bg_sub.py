from __future__ import annotations

import logging

from bg_sub import bg_sub

from fits.workflows.experiments import ExperimentState
from fits.settings.models import BGSubSettings
from fits.tasks.common.artifact_results import save_step_result
from fits.tasks.common.preparation import load_input_reader, resolve_step_run
from fits.workflows.definitions.models import StepProfile
from fits.workflows.runtime.errors import StepExecutionError


logger = logging.getLogger(__name__)


def remove_bg(settings: BGSubSettings, 
              exp_state: ExperimentState, 
              step_profile: StepProfile
              ) -> list[ExperimentState]:
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
    try:
        reader = load_input_reader(exp_state, step_profile)
        run = resolve_step_run(exp_state, step_profile, settings.overwrite)
        if run.is_complete:
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

        new_st = save_step_result(reader=reader,
                                array=corrected_array,
                                export_channels=reader.channel_labels,
                                updated_state=updated_state,
                                step_profile=step_profile,)
        return [new_st]
    
    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        raise StepExecutionError(
            f"Step {str(step_profile.step_name)!r} failed for "
            f"{exp_state.experiment_id}: {e}") from e
