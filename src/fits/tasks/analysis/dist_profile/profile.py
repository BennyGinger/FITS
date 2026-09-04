from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

from fits.environment.state import ExperimentState
from fits.settings.models import DistanceProfileSettings
from fits.tasks.analysis.dist_profile.manager import DistanceProfileManager
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import decide_run
from fits.workflows.errors import StepExecutionError


logger = logging.getLogger(__name__)


def run_distance_profile(settings: DistanceProfileSettings,
                         exp_state: ExperimentState,
                         step_profile: StepProfile,
                         ) -> list[ExperimentState]:
    """Calculate and save one experiment's binned distance profile."""
    try:
        run = decide_run(exp_state, step_profile, settings.overwrite)
        if run.is_complete:
            return [exp_state]

        dataframe = DistanceProfileManager(exp_state, settings).calculate()
        output_path = exp_state.workdir / step_profile.output_name
        save_path = _save_distance_profile(dataframe, output_path)
        updated_state = exp_state.with_metadata(
            step_name=step_profile.step_name,
            created_by=step_profile.distribution,
            channels_params=settings.model_dump(),)
        new_state = updated_state.with_complete_step(
            step_name=step_profile.step_name,
            artifact_kind=step_profile.output_artifact,
            artifact_path=save_path,)
        new_state.save_state()
        return [new_state]
    except Exception as exc:
        logger.exception(
            "%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        raise StepExecutionError(
            f"Step {step_profile.step_name!r} failed for "
            f"{exp_state.experiment_id}: {exc}") from exc


def _save_distance_profile(dataframe: pd.DataFrame, output_path: Path) -> Path:
    """Atomically save one distance-profile table."""
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    try:
        dataframe.to_parquet(temporary_path, index=False)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        logger.error("Failed to save distance profile to %s", output_path)
        raise
    return output_path
