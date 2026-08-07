from __future__ import annotations

import logging

from fits_io.client import FitsIO
from tracklink.api import TrackModel

from fits.environment.constant import ARTI_IMG
from fits.environment.state import ExperimentState
from fits.settings.models import TrackSettings
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import decide_run


logger = logging.getLogger(__name__)


def track(settings: TrackSettings, exp_state: ExperimentState, step_profile: StepProfile) -> list[ExperimentState]:
    """
    Process a single experiment through the track step.

    Args:
        settings: Track step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
    
    Returns:
        List of one output experiment state. Track step produces a single output artifact.
    """
    input_path = exp_state.artifact(step_profile.input_artifact) # i.e. seg_mask
    if input_path is None:
        logger.error("%s failed for loading %s: missing input",
                        step_profile.step_name,
                        step_profile.input_artifact)
        return []

    try:
        mask_reader = FitsIO.from_path(input_path)
        # Run step?
        requested_seg_idxs = mask_reader.labels_to_indices(settings.channel_to_track)
        run = decide_run(exp_state, step_profile, settings.overwrite, requested_seg_idxs)
        if run.is_complete:
            logger.debug("Skipping %s for %s: all requested channels already covered.",
                            step_profile.step_name, 
                            exp_state.experiment_id)
            return [exp_state]
        
        track_idx = run.pending_items
        input_labels = mask_reader.indices_to_labels(track_idx)
        
        input_mask = mask_reader.get_channel(input_labels)
        logger.debug("%s will be executed for channel(s): %s", 
                     step_profile.step_name, 
                     input_labels)
        
        # Get the image array
        image_path = exp_state.artifact(ARTI_IMG)
        if image_path is None:
            logger.error("%s failed for loading %s: missing input",
                         step_profile.step_name,
                         ARTI_IMG)
            return []
        image_reader = FitsIO.from_path(image_path)
        input_image = image_reader.get_channel(input_labels)
        
        # Get specific settings for the selected backend
        backend_settings = getattr(settings, settings.backend, {})
        
        # Initialize model
        tracking = TrackModel(backend=settings.backend)
        tracking.configure(backend_settings)
        
        # Run tracking
        tracking.track(input_image.array, input_mask.array) 
        filtered_mask = tracking.filter_by_length(min_length=settings.filter_by_length)
        
        output_path = exp_state.artifact(step_profile.output_artifact)
        if output_path is None or settings.overwrite:
            existing_reader = None
        else:
            existing_reader = FitsIO.from_path(output_path)
        merging = mask_reader.merge_channels(existing=existing_reader,
                                             new_array=filtered_mask,
                                             new_axes=input_mask.axes,
                                             new_channel_indices=track_idx,)
        
        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                exported_channel=merging.channel_indices,
                                                channels_params=settings.to_payload_dict(),)
        
        merged_labels = mask_reader.indices_to_labels(merging.channel_indices)
        logger.debug("Mask save payload: shape=%s, axes=%s, labels=%s",
                             merging.array.shape,
                             merging.axes,
                             merged_labels,)
        
        save_path = mask_reader.save_array(merging.array,
                                           output_name=step_profile.output_name,
                                           export_channels=merged_labels,
                                           artifact_kind=step_profile.output_artifact,
                                           created_by=step_profile.distribution,
                                           custom_metadata=updated_state.metadata_dump,)
        
        logger.debug("%s completed for %s", step_profile.step_name, exp_state.experiment_id)
        
        new_st = updated_state.with_complete_step(step_name=step_profile.step_name,
                                                artifact_kind=step_profile.output_artifact,
                                                artifact_path=save_path,)
        
        logger.debug("Produced new ExperimentState: %s", new_st)
        new_st.save_state()
        return [new_st]

    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        print(f"[ERROR] Step '{step_profile.step_name}' failed for {exp_state.experiment_id}: {e}")
        return []
