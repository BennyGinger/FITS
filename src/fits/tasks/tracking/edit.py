from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from fits.environment.constant import (
    ARTI_IMG,
    DIST_FITS,
    FITS_MASK_TRACK,
    FITS_MASK_TRACK_EDITED,
    FITS_MASK_TRACK_EDITED_FILTERED,
)
from fits.tasks.common.artifact_results import complete_step_result
from fits.workflows.definitions.models import StepProfile
from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import StepExecutionError


logger = logging.getLogger(__name__)


def register_tracking_edit(exp_state: ExperimentState,
                           step_profile: StepProfile,
                           artifact_path: Path,
                           edit_metadata: Mapping[str, Any],
                           ) -> ExperimentState:
    """Register the tracking artifact finalized by the interactive editor."""
    try:
        source_path = exp_state.artifact(step_profile.input_artifact)
        image_path = exp_state.artifact(ARTI_IMG)
        saved_path = Path(artifact_path).expanduser().resolve()
        if source_path is None or not source_path.is_file():
            raise StepExecutionError(
                f"Step {str(step_profile.step_name)!r} failed for "
                f"{exp_state.experiment_id}: missing tracking input.")
        if image_path is None or not image_path.is_file():
            raise StepExecutionError(
                f"Step {str(step_profile.step_name)!r} failed for "
                f"{exp_state.experiment_id}: missing image input.")
        if not saved_path.is_file():
            raise StepExecutionError(
                f"Edited tracking artifact does not exist: {saved_path}")
        if saved_path.name not in {
                FITS_MASK_TRACK,
                FITS_MASK_TRACK_EDITED,
                FITS_MASK_TRACK_EDITED_FILTERED}:
            raise StepExecutionError(
                f"Unexpected edited tracking filename: {saved_path.name}")
        if saved_path.parent != source_path.parent:
            raise StepExecutionError(
                "Edited tracking artifacts must be saved beside their source tracking file.")

        updated_state = exp_state.with_metadata(
            step_name=step_profile.step_name,
            created_by=DIST_FITS,
            exported_channel="all",
            channels_params=dict(edit_metadata),)
        return complete_step_result(updated_state, step_profile, saved_path)

    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name,
                         exp_state.experiment_id)
        if isinstance(e, StepExecutionError):
            raise
        raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for "
                                 f"{exp_state.experiment_id}: {e}") from e
