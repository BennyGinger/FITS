# from __future__ import annotations

# import logging
# from typing import cast

# from fits_io.client import FitsIO
# from tracklink.api import TrackModel

# from fits.environment.constant import StepName
# from fits.environment.state import ExperimentState
# from fits.settings.models import TrackSettings
# from fits.workflows.engines.models import StepProfile
# from fits.workflows.metadata.channel_identity import labels_to_src_indices, src_indices_to_labels
# from fits.workflows.engines.run_decision import decide_run
# from fits.workflows.arrays.merging import merge_channel
# from fits.workflows.arrays.loading import get_array


# logger = logging.getLogger(__name__)


# def track_one(settings: TrackSettings, exp_state: ExperimentState, step_profile: StepProfile) -> list[ExperimentState]:
#     """
#     Process a single experiment through the track step.

#     Args:
#         settings: Track step settings
#         exp_state: Single experiment state to process
#         step_profile: Step metadata
#     Returns:
#         Single output experiment state.
#     """
#     if exp_state.image is None:
#         logger.error("%s failed for %s: missing image input", step_profile.step_name, exp_state.original_image)
#         return []

#     if exp_state.seg_masks is None:
#         logger.error("%s failed for %s: missing segmentation masks input", step_profile.step_name, exp_state.original_image)
#         return []
    
#     chan_track = list(settings.channel_to_track)
    
#     try:
#         reader = FitsIO.from_path(exp_state.seg_masks)
#         logger.debug("Loaded masks from %s", exp_state.seg_masks)
#         requested_track_src_idxs = labels_to_src_indices(reader, chan_track, exp_state)
#         run = decide_run(exp_state, step_profile.step_name, settings.overwrite, requested_track_src_idxs)
        
#         if run.is_complete:
#             logger.debug("Skipping %s for %s: all requested channels already covered.", step_profile.step_name, exp_state.original_image)
#             return [exp_state]
        
#         track_src_chan_idx = cast(list[int], run.pending_items)
#         missing_track_labels = src_indices_to_labels(reader, track_src_chan_idx, exp_state)
#         requested_channels = list(dict.fromkeys(missing_track_labels))
#         logger.debug("%s will be executed for channel(s): %s", step_profile.step_name, requested_channels)
        
#         # Get image array and associated axis order
#         image_reader = FitsIO.from_path(exp_state.image)
#         input_array, _ = get_array(image_reader, requested_channels)
#         mask_array, mask_axis_order = get_array(reader, requested_channels)
        
#         # Get specific settings for the selected backend
#         backend_settings = getattr(settings, settings.backend, {})
        
#         # Initialize model
#         tracking = TrackModel(backend=settings.backend)
#         tracking.configure(backend_settings)
        
#         # Run tracking
#         tracking.track(input_array, mask_array) 
#         filtered_mask = tracking.filter_by_length(min_length=settings.filter_by_length)
#         out_axis_order = mask_axis_order
        
#         existing_array = None
#         existing_axes = None
#         existing_channel_indices = None

#         existing_mask_path = None if settings.overwrite else exp_state.track_masks
#         if existing_mask_path is not None:
#             existing_reader = FitsIO.from_path(existing_mask_path)
#             existing_array = existing_reader.get_array()
#             existing_axes = existing_reader.axes
#             existing_channel_indices = existing_reader.artifact_channel_indices

#         merged_array, merged_axes, merged_channel_indices = merge_channel(
#             existing_array=existing_array,
#             existing_axes=existing_axes,
#             existing_channel_indices=existing_channel_indices,
#             new_array=filtered_mask,
#             new_axes=out_axis_order,
#             new_channel_indices=track_src_chan_idx,
#             reference_axes=reader.axes,
#         )

#         merged_labels = reader.labels_for_source_indices(merged_channel_indices)
#         updated_state = exp_state.with_metadata(
#             step_name=step_profile.step_name,
#             created_by=step_profile.distribution,
#             exported_channel_indices=merged_channel_indices,
#             channels_params={
#                 "track_backend": settings.backend,
#                 "filter_by_length": settings.filter_by_length,
#                 "backend_settings": backend_settings,
#             },
#         )
#         logger.debug("Mask save payload: shape=%s, axes=%s, labels=%s", merged_array.shape, merged_axes, merged_labels)
        
#         # Save
#         save_path = reader.save_array(
#             merged_array,
#             output_name=step_profile.output_name,
#             export_channels=merged_labels,
#             artifact_kind="tracking",
#             created_by=step_profile.distribution,
#             custom_metadata=updated_state.metadata_dump,
#         )
#         logger.debug("%s completed for %s", step_profile.step_name, exp_state.workdir)
        
#         # Update experiment state
#         new_st = updated_state.with_step_result(
#             step_name=step_profile.step_name,
#             artifact_kind=step_profile.output_artifact,
#             artifact_path=save_path,
#         )
#         logger.debug("Produced new ExperimentState: %s", new_st)
#         new_st.save_state()
#         return [new_st]
    
#     except Exception as e:
#         logger.exception("%s failed for %s", step_profile.step_name, exp_state.workdir)
#         print(f"[ERROR] Step '{step_profile.step_name}' failed for {exp_state.workdir}: {e}")
#         return []