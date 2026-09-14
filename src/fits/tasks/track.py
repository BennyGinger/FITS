from __future__ import annotations

import logging
import numpy as np

from fits_io.client import FitsIO
from fits_io.writers.apis import merge_channel_arrays
from fits_io.writers.models import ChannelMergeResult
from tracklink.api import TrackModel

from fits.environment.constant import ARTI_IMG
from fits.environment.state import ExperimentState
from fits.settings.models import TrackSettings
from fits.tracking_postprocess import StaticMaskPostprocessor
from fits.tracking_postprocess import StaticPostprocessConfig
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import decide_run
from fits.workflows.errors import StepExecutionError


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
        raise StepExecutionError(
            f"Step {str(step_profile.step_name)!r} failed for {exp_state.experiment_id}: "
            f"missing {step_profile.input_artifact!r} input.")

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
        
        logger.debug("%s will be executed for channel(s): %s", 
                     step_profile.step_name, 
                     input_labels)
        
        # Get the image array
        image_path = exp_state.artifact(ARTI_IMG)
        if image_path is None:
            raise StepExecutionError(
                f"Step {str(step_profile.step_name)!r} failed for {exp_state.experiment_id}: "
                f"missing {ARTI_IMG!r} input.")
        image_reader = FitsIO.from_path(image_path)
        
        # Get specific settings for the selected backend
        backend_settings = getattr(settings, settings.backend, {})
        
        # Initialize model
        tracking = TrackModel(backend=settings.backend)
        tracking.configure(backend_settings)
        
        postprocessor = None
        if settings.postprocess.enabled:
            postprocess_config = StaticPostprocessConfig(
                shape_similarity=settings.postprocess.shape_similarity,
                minimum_appearances=settings.postprocess.minimum_appearances,
                extrapolate_start=settings.postprocess.extrapolate_start,
                extrapolate_end=settings.postprocess.extrapolate_end,)
            postprocessor = StaticMaskPostprocessor(postprocess_config)

        # Backends receive one channel's time series, never a C dimension.
        # Keep all results in memory until every requested channel succeeds.
        new_results: ChannelMergeResult | None = None
        for channel_index, channel_label in zip(track_idx, input_labels, strict=True):
            try:
                input_mask = mask_reader.get_channel(channel_label)
                input_image = image_reader.get_channel(channel_label)
                axes = "TZYX" if "Z" in input_mask.axes else "TYX"
                if (set(input_mask.axes) != set(axes)
                        or set(input_image.axes) != set(axes)):
                    raise ValueError(
                        f"Tracking requires a single-channel time series ({axes}); "
                        f"image axes={input_image.axes}, mask axes={input_mask.axes}.")
                mask_array = np.transpose(
                    input_mask.array, [input_mask.axes.index(axis) for axis in axes])
                image_array = np.transpose(
                    input_image.array, [input_image.axes.index(axis) for axis in axes])
                if image_array.shape != mask_array.shape:
                    raise ValueError(
                        f"Image shape {image_array.shape} does not match mask shape {mask_array.shape}.")
                logger.debug("Tracking channel '%s': shape=%s, axes=%s",
                             channel_label, mask_array.shape, axes)
                tracked_mask = tracking.track(image_array, mask_array)
                if postprocessor is not None:
                    tracked_mask = postprocessor.process(tracked_mask)
                if tracked_mask.shape != mask_array.shape:
                    raise ValueError("Tracker output shape does not match its input mask.")
                tracked_mask = np.transpose(
                    tracked_mask, [axes.index(axis) for axis in input_mask.axes])
                if new_results is None:
                    new_results = ChannelMergeResult(
                        array=tracked_mask, axes=input_mask.axes,
                        channel_indices=[channel_index])
                else:
                    new_results = merge_channel_arrays(
                        existing_array=new_results.array,
                        existing_axes=new_results.axes,
                        existing_channel_indices=new_results.channel_indices,
                        new_array=tracked_mask,
                        new_axes=input_mask.axes,
                        new_channel_indices=[channel_index],
                        reference_axes=mask_reader.axes)
            except Exception as exc:
                raise StepExecutionError(
                    f"Step '{step_profile.step_name}' failed for {exp_state.experiment_id}, "
                    f"channel {channel_label!r}: {exc}") from exc

        if new_results is None:
            raise ValueError("No pending tracking channels were resolved.")
        
        output_path = exp_state.artifact(step_profile.output_artifact)
        if output_path is None or settings.overwrite:
            existing_reader = None
        else:
            existing_reader = FitsIO.from_path(output_path)
        merging = mask_reader.merge_channels(existing=existing_reader,
                                             new_array=new_results.array,
                                             new_axes=new_results.axes,
                                             new_channel_indices=new_results.channel_indices,)
        
        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                exported_channel=track_idx,
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
        
        logger.debug("Produced new ExperimentState: exp_id=%s completed_steps=%s",
                     new_st.experiment_id, [str(step) for step in new_st.completed_steps])
        new_st.save_state()
        return [new_st]

    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        if isinstance(e, StepExecutionError):
            raise
        raise StepExecutionError(
            f"Step {str(step_profile.step_name)!r} failed for "
            f"{exp_state.experiment_id}: {e}") from e
