from __future__ import annotations
import logging
import numpy as np
from pathlib import Path
from scope_io.client import ScopeIO
from fits.workflows.experiments import ExperimentState, save_experiment_state
from fits.workflows.definitions.models import StepProfile
from fits.workflows.artifacts.provenance import revision_payload


logger = logging.getLogger(__name__)


def save_step_result(reader: ScopeIO,
                     array: np.ndarray,
                     export_channels: list[str],
                     updated_state: ExperimentState,
                     step_profile: StepProfile,
                     ) -> ExperimentState:
    """
    Save an array artifact and persist the completed experiment state.
    """
    payload = revision_payload(reader, updated_state, step_profile, export_channels=export_channels)
    save_path = reader.save_array(array,
                                  output_path=updated_state.workdir / step_profile.output_name,
                                  metadata=payload,
                                  )

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
                                                 artifact_path=artifact_path,
                                                 )
    logger.debug("%s completed for %s", step_profile.step_name, new_state.experiment_id)
    logger.debug("Produced new ExperimentState: exp_id=%s completed_steps=%s",
                 new_state.experiment_id,
                 [str(step) for step in new_state.completed_steps],
                 )
    save_experiment_state(new_state)
    return new_state
