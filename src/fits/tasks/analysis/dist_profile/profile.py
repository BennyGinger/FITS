from __future__ import annotations

import logging

from fits.workflows.experiments import ExperimentState
from fits.settings.models import DistanceProfileSettings
from fits.tasks.analysis.dist_profile.manager import DistanceProfileManager
from fits.tasks.common.artifact_results import complete_step_result
from fits.tasks.common.preparation import resolve_step_run
from fits.tasks.common.table_results import save_parquet
from fits.workflows.definitions.models import StepProfile
from fits.workflows.runtime.errors import StepExecutionError


logger = logging.getLogger(__name__)


def run_distance_profile(settings: DistanceProfileSettings,
                         exp_state: ExperimentState,
                         step_profile: StepProfile,
                         ) -> list[ExperimentState]:
    """Calculate and save one experiment's binned distance profile."""
    try:
        run = resolve_step_run(exp_state, step_profile, settings.overwrite)
        if run.is_complete:
            return [exp_state]

        dataframe = DistanceProfileManager(exp_state, settings).calculate()
        output_path = exp_state.workdir / step_profile.output_name

        save_path = save_parquet(dataframe, output_path)

        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                channels_params=settings.model_dump(),)
        new_state = complete_step_result(updated_state,
                                        step_profile,
                                        save_path,)
        return [new_state]

    except Exception as exc:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for "
                                f"{exp_state.experiment_id}: {exc}") from exc
