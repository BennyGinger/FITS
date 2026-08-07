from __future__ import annotations

import logging

from fits_io import FitsIO

from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import decide_run
from fits.tasks.segmentation.model_cache import segment_model_cache


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
    input_path = exp_state.artifact(step_profile.input_artifact)
    if input_path is None:
        logger.error("%s failed for loading %s: missing input",
                     step_profile.step_name,
                     step_profile.input_artifact)
        return []

    try:
        reader = FitsIO.from_path(input_path)
        # Run step?
        requested_seg_idxs = reader.labels_to_indices(settings.channel_to_segment)
        run = decide_run(exp_state, step_profile, settings.overwrite, requested_seg_idxs)
        if run.is_complete:
            logger.debug("Skipping %s for %s: all requested channels already covered.",
                         step_profile.step_name, 
                         exp_state.experiment_id)
            return [exp_state]
        
        # Get the input array
        seg_idx = run.pending_items
        seg_labels = reader.indices_to_labels(seg_idx)
        
        input_labels = seg_labels
        if settings.nuclear_channel is not None:
            if settings.nuclear_channel in input_labels:
                logger.warning("Nuclear channel '%s' is already in the segmentation channels %s; it will then be ignored.", 
                               settings.nuclear_channel,
                               input_labels)
            input_labels = list(dict.fromkeys([*seg_labels, settings.nuclear_channel]))  # Ensure unique labels while preserving order
            
        input_results = reader.get_channel(input_labels)
        
        logger.debug("%s will be executed for channel(s): %s", step_profile.step_name, input_labels)

        # Get the segmentation model wrapper
        cp_wrapper = segment_model_cache.get_wrapper(segment_settings=settings.model_dump())

        # Run the segmentation model on the input array
        masks_array = cp_wrapper.run(input_results.array, input_results.axes)

        out_axis_order = cp_wrapper.output_axis_order
        if out_axis_order is None:
            raise ValueError("Segment model wrapper did not provide an output axis order.")

        # Merging existing masks with new masks if not overwriting
        output_path = exp_state.artifact(step_profile.output_artifact)
        if output_path is None or settings.overwrite:
            existing_reader = None
        else:
            existing_reader = FitsIO.from_path(output_path)
        merging = reader.merge_channels(existing=existing_reader,
                                        new_array=masks_array,
                                        new_axes=out_axis_order,
                                        new_channel_indices=seg_idx,)
        
        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                exported_channel=merging.channel_indices,
                                                channels_params=settings.to_payload_dict(),)
        
        merged_labels = reader.indices_to_labels(merging.channel_indices)
        logger.debug("Mask save payload: shape=%s, axes=%s, labels=%s",
                     merging.array.shape,
                     merging.axes,
                     merged_labels,)

        save_path = reader.save_array(merging.array,
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