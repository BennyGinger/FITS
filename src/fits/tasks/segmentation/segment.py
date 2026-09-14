from __future__ import annotations

import logging

from cellpose_kit.client import CellposeWrapper
from fits_io import FitsIO
from fits_io.writers.apis import merge_channel_arrays
from fits_io.writers.models import ChannelMergeResult

from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import decide_run
from fits.workflows.errors import StepExecutionError


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
        raise StepExecutionError(
            f"Step {str(step_profile.step_name)!r} failed for {exp_state.experiment_id}: "
            f"missing {step_profile.input_artifact!r} input.")

    try:
        if not settings.channels:
            raise ValueError("At least one segmentation channel must be configured.")
        reader = FitsIO.from_path(input_path)
        # Run step?
        target_labels = [entry.channel for entry in settings.channels]
        requested_seg_idxs = reader.labels_to_indices(target_labels)
        run = decide_run(exp_state, step_profile, settings.overwrite, requested_seg_idxs)
        if run.is_complete:
            logger.debug("Skipping %s for %s: all requested channels already covered.",
                         step_profile.step_name, 
                         exp_state.experiment_id)
            return [exp_state]
        
        # Get the input array
        pending_indices = set(run.pending_items)
        pending_entries = [
            (entry, index)
            for entry, index in zip(settings.channels, requested_seg_idxs, strict=True)
            if index in pending_indices
        ]

        new_results: ChannelMergeResult | None = None
        for channel_settings, channel_index in pending_entries:
            input_labels = [channel_settings.channel]
            if channel_settings.nuclear_channel is not None:
                if channel_settings.nuclear_channel == channel_settings.channel:
                    logger.warning(
                        "Nuclear channel '%s' is also the segmentation target; "
                        "it will be supplied only once.",
                        channel_settings.channel,
                    )
                else:
                    input_labels.append(channel_settings.nuclear_channel)

            input_results = reader.get_channel(input_labels)
            logger.debug(
                "%s will segment target channel '%s' using input channel(s): %s",
                step_profile.step_name,
                channel_settings.channel,
                input_labels,
            )

            try:
                cp_wrapper = CellposeWrapper.from_dict(
                    channel_settings.cellpose_payload(threading=settings.threading)
                )
                cp_wrapper.setup()
                masks_array = cp_wrapper.run(input_results.array, input_results.axes)
                out_axis_order = cp_wrapper.output_axis_order
                if out_axis_order is None:
                    raise ValueError("Segment model wrapper did not provide an output axis order.")
            except Exception as exc:
                raise RuntimeError(
                    f"Segmentation failed for channel {channel_settings.channel!r}: {exc}"
                ) from exc

            if new_results is None:
                new_results = ChannelMergeResult(
                    array=masks_array,
                    axes=out_axis_order,
                    channel_indices=[channel_index],
                )
            else:
                new_results = merge_channel_arrays(
                    existing_array=new_results.array,
                    existing_axes=new_results.axes,
                    existing_channel_indices=new_results.channel_indices,
                    new_array=masks_array,
                    new_axes=out_axis_order,
                    new_channel_indices=[channel_index],
                    reference_axes=reader.axes,
                )

        if new_results is None:
            raise RuntimeError("No pending segmentation channels were resolved.")

        # Merging existing masks with new masks if not overwriting
        output_path = exp_state.artifact(step_profile.output_artifact)
        if output_path is None or settings.overwrite:
            existing_reader = None
        else:
            existing_reader = FitsIO.from_path(output_path)
        merging = reader.merge_channels(existing=existing_reader,
                                        new_array=new_results.array,
                                        new_axes=new_results.axes,
                                        new_channel_indices=new_results.channel_indices,)

        updated_state = exp_state
        for channel_settings, channel_index in pending_entries:
            updated_state = updated_state.with_metadata(
                step_name=step_profile.step_name,
                created_by=step_profile.distribution,
                exported_channel=[channel_index],
                channels_params=channel_settings.to_payload_dict(),
            )
        
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
        
        logger.debug("Produced new ExperimentState: exp_id=%s completed_steps=%s",
                     new_st.experiment_id, [str(step) for step in new_st.completed_steps])
        new_st.save_state()
        return [new_st]

    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        raise StepExecutionError(
            f"Step {str(step_profile.step_name)!r} failed for "
            f"{exp_state.experiment_id}: {e}") from e
