from pathlib import Path

import pandas as pd

from fits.environment.constant import (
    ARTI_DIST_PROF,
    ARTI_IMG,
    DIST_DISTANCE_PROFILE,
    FITS_DISTANCE_PROFILE_NAME,
    StepName,
)
from fits.environment.state import ExperimentState
from fits.settings.models import DistanceProfileSettings
from fits.tasks.analysis.dist_profile.profile import run_distance_profile
from fits.workflows.engines.models import StepProfile


def test_distance_profile_task_saves_and_registers_artifact(
        tmp_path: Path, monkeypatch,) -> None:
    image_path = tmp_path / "fits_array.tif"
    image_path.touch()
    state = ExperimentState(
        workdir=tmp_path,
        artifacts={ARTI_IMG: image_path},)
    expected = pd.DataFrame({
        "experiment_id": [state.experiment_id],
        "frame": [1],
        "mean_intensity": [12.0],
    })

    monkeypatch.setattr(
        "fits.tasks.analysis.dist_profile.profile.DistanceProfileManager.calculate",
        lambda self: expected,)
    profile = StepProfile(
        step_name=StepName.DISTANCE_PROFILE,
        distribution=DIST_DISTANCE_PROFILE,
        input_artifact=ARTI_IMG,
        output_artifact=ARTI_DIST_PROF,
        output_name=FITS_DISTANCE_PROFILE_NAME,)

    result = run_distance_profile(
        DistanceProfileSettings(),
        state,
        profile,)[0]

    output_path = tmp_path / FITS_DISTANCE_PROFILE_NAME
    assert result.artifact(ARTI_DIST_PROF) == output_path
    assert StepName.DISTANCE_PROFILE in result.completed_steps
    pd.testing.assert_frame_equal(pd.read_parquet(output_path), expected)
    assert (tmp_path / "experiment_state.json").is_file()
