import logging
from pathlib import Path

import numpy as np
from fits_io.client import FitsIO

from fits.workflows.experiments import ExperimentState, save_experiment_state
from fits.workflows.definitions.models import StepProfile


logger = logging.getLogger(__name__)


def save_step_result(reader: FitsIO,
                    array: np.ndarray,
                    export_channels: list[str],
                    updated_state: ExperimentState,
                    step_profile: StepProfile,
                    ) -> ExperimentState:
    """
    Save an array artifact and persist the completed experiment state.
    """
    save_path = reader.save_array(array,
                                output_name=step_profile.output_name,
                                export_channels=export_channels,
                                artifact_kind=step_profile.output_artifact,
                                created_by=step_profile.distribution,
                                custom_metadata=updated_state.metadata_dump,)

    return complete_step_result(updated_state, step_profile, save_path)


def complete_step_result(updated_state: ExperimentState,
                        step_profile: StepProfile,
                        artifact_path: Path,
                        ) -> ExperimentState:
    """
    Mark an artifact-producing step complete and persist its state.
    """
    new_state = updated_state.with_complete_step(step_name=step_profile.step_name,
                                                artifact_kind=step_profile.output_artifact,
                                                artifact_path=artifact_path,)
    logger.debug("%s completed for %s",
                step_profile.step_name,
                new_state.experiment_id,)
    logger.debug("Produced new ExperimentState: exp_id=%s completed_steps=%s",
                new_state.experiment_id,
                [str(step) for step in new_state.completed_steps],)
    save_experiment_state(new_state)
    return new_state
