"""Progress identifiers shared by interactive workflow paths."""

from fits.environment.constant import ARTI_IMG
from fits.workflows.experiments import ExperimentState


def input_progress_id(state: ExperimentState) -> str:
    """
    Identify raw inputs without collapsing materialized series branches.
    """
    if ARTI_IMG in state.artifacts:
        return state.experiment_id
    try:
        return state.original_image.as_posix()
    except KeyError:
        return state.experiment_id
