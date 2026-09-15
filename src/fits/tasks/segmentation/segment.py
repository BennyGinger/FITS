from __future__ import annotations

import logging

from fits.workflows.experiments import ExperimentState
from fits.settings.models import SegmentSettings
from fits.tasks.common.artifact_results import save_step_result
from fits.tasks.common.channel_results import merge_channel_results
from fits.tasks.common.preparation import load_input_reader, resolve_step_run
from fits.tasks.segmentation.channels import resolve_pending_entries, segment_channels
from fits.workflows.definitions.models import StepProfile
from fits.workflows.runtime.errors import StepExecutionError


logger = logging.getLogger(__name__)


def segment(settings: SegmentSettings, exp_state: ExperimentState, step_profile: StepProfile) -> list[ExperimentState]:
    """
    Process a single experiment through the segmentation step.
    
    Args:
        settings: Segmentation step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
        
    Returns:
        List of one output experiment state. Segmentation step produces a single output artifact.
    """
    try:
        if not settings.channels:
            raise ValueError("At least one segmentation channel must be configured.")

        reader = load_input_reader(exp_state, step_profile)
        target_labels = [entry.channel for entry in settings.channels]
        requested_seg_idxs = reader.labels_to_indices(target_labels)
        run = resolve_step_run(exp_state,
                            step_profile,
                            settings.overwrite,
                            requested_seg_idxs,)
        if run.is_complete:
            return [exp_state]
        
        pending_entries = resolve_pending_entries(settings,
                                                requested_seg_idxs,
                                                run.pending_items,)
        new_results = segment_channels(reader,
                                    pending_entries,
                                    settings.threading,
                                    step_profile,)

        merging = merge_channel_results(reader=reader,
                                        new_results=new_results,
                                        output_path=exp_state.artifact(step_profile.output_artifact),
                                        overwrite=settings.overwrite,)

        updated_state = exp_state
        for channel_settings, channel_index in pending_entries:
            updated_state = updated_state.with_metadata(step_name=step_profile.step_name,
                                                        created_by=step_profile.distribution,
                                                        exported_channel=[channel_index],
                                                        channels_params=channel_settings.to_payload_dict(),)
        
        merged_labels = reader.indices_to_labels(merging.channel_indices)
        logger.debug("Mask save payload: shape=%s, axes=%s, labels=%s",
                     merging.array.shape,
                     merging.axes,
                     merged_labels,)

        new_st = save_step_result(reader=reader,
                                array=merging.array,
                                export_channels=merged_labels,
                                updated_state=updated_state,
                                step_profile=step_profile,)
        return [new_st]

    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        raise StepExecutionError(
            f"Step {str(step_profile.step_name)!r} failed for "
            f"{exp_state.experiment_id}: {e}") from e
