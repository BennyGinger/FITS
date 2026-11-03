from __future__ import annotations

from collections.abc import Sequence
import logging
from fits_io.client import FitsIO
from fits.workflows.experiments import ExperimentState
from fits.workflows.definitions.models import StepProfile
from fits.workflows.definitions.inputs import resolve_inputs
from fits.workflows.runtime.run_decision import RunDecision, decide_run
from fits.workflows.runtime.errors import StepExecutionError
from fits.workflows.checks.space import require_processing_space


logger = logging.getLogger(__name__)


def load_input_reader(exp_state: ExperimentState, step_profile: StepProfile) -> FitsIO:
    """
    Open the required input artifact for an array-processing step.
    """
    input_path = next(iter(resolve_inputs(exp_state, step_profile).values()))
    if input_path is None:
        raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for "
                                f"{exp_state.experiment_id}: missing "
                                f"{step_profile.input_artifact!r} input.")
    return FitsIO.from_path(input_path)


def resolve_step_run(exp_state: ExperimentState,
                     step_profile: StepProfile,
                     overwrite: bool,
                     requested_items: Sequence[int] | None = None,
                     ) -> RunDecision:
    """
    Resolve pending work and log when a step is already complete.
    """
    run = decide_run(exp_state, step_profile, overwrite, requested_items)
    if run.is_complete:
        logger.debug("Skipping %s for %s: requested work is already complete.",
                     step_profile.step_name,
                     exp_state.experiment_id,
                     )
    else:
        require_processing_space(exp_state.run_dir or exp_state.workdir, ((exp_state, 1),))
    return run
