from __future__ import annotations

import logging

from fits_io.client import FitsIO

from fits.environment.constant import ARTI_IMG
from fits.workflows.experiments import ExperimentState
from fits.settings.models import TrackSettings
from fits.tasks.common.artifact_results import save_step_result
from fits.tasks.common.channel_results import merge_channel_results
from fits.tasks.common.preparation import load_input_reader, resolve_step_run
from fits.tasks.tracking.channels import track_channels
from fits.tasks.tracking.backend import create_tracker
from fits.workflows.definitions.models import StepProfile
from fits.workflows.runtime.errors import StepExecutionError

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
    try:
        mask_reader = load_input_reader(exp_state, step_profile)
        requested_seg_idxs = mask_reader.labels_to_indices(settings.channel_to_track)
        run = resolve_step_run(exp_state,
                            step_profile,
                            settings.overwrite,
                            requested_seg_idxs,)
        if run.is_complete:
            return [exp_state]

        track_idx = run.pending_items
        input_labels = mask_reader.indices_to_labels(track_idx)

        logger.debug("%s will be executed for channel(s): %s", step_profile.step_name,
                        input_labels)

        # Get the image array
        image_path = exp_state.artifact(ARTI_IMG)
        if image_path is None:
            raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for {exp_state.experiment_id}: "
                                    f"missing {step_profile.input_artifact!r} input.")
        image_reader = FitsIO.from_path(image_path)

        tracker = create_tracker(settings)

        # Backends receive one channel's time series, never a C dimension.
        # Keep all results in memory until every requested channel succeeds.
        new_results = track_channels(tracker=tracker,
                                    postprocess_settings=settings.postprocess,
                                    mask_reader=mask_reader,
                                    image_reader=image_reader,
                                    channel_indices=track_idx,
                                    channel_labels=input_labels,
                                    step_profile=step_profile,
                                    exp_state=exp_state,)

        merging = merge_channel_results(reader=mask_reader,
                                        new_results=new_results,
                                        output_path=exp_state.artifact(step_profile.output_artifact),
                                        overwrite=settings.overwrite,)

        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                exported_channel=track_idx,
                                                channels_params=settings.to_payload_dict(),)

        merged_labels = mask_reader.indices_to_labels(merging.channel_indices)
        logger.debug("Mask save payload: shape=%s, axes=%s, labels=%s",
                    merging.array.shape,
                    merging.axes,
                    merged_labels,)

        new_st = save_step_result(reader=mask_reader,
                                array=merging.array,
                                export_channels=merged_labels,
                                updated_state=updated_state,
                                step_profile=step_profile,)
        return [new_st]

    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name,
                            exp_state.experiment_id)
        if isinstance(e, StepExecutionError):
            raise
        raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for "
                                    f"{exp_state.experiment_id}: {e}") from e
