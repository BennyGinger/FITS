from pathlib import Path

import pandas as pd

from fisch.environment.constant import (
    ARTI_DIST_PROF,
    ARTI_IMG,
    DIST_DISTANCE_PROFILE,
    DISTANCE_PROFILE_NAME,
    StepName,
)
from fisch.workflows.experiments import ExperimentState
from fisch.settings.models import DistanceProfileSettings
from fisch.tasks.analysis.dist_profile.profile import run_distance_profile
from fisch.workflows.definitions.models import StepProfile


def test_distance_profile_task_saves_and_registers_artifact(
        tmp_path: Path, monkeypatch,) -> None:
    image_path = tmp_path / "proc_array.tif"
    import numpy as np
    import tifffile
    tifffile.imwrite(image_path, np.ones((8, 8), dtype=np.uint16), photometric="minisblack")
    state = ExperimentState(
        workdir=tmp_path,
        artifacts={ARTI_IMG: image_path, "raw_image": image_path},)
    expected = pd.DataFrame({
        "experiment_id": [state.experiment_id],
        "frame": [1],
        "mean_intensity": [12.0],
    })

    monkeypatch.setattr(
        "fisch.tasks.analysis.dist_profile.profile.DistanceProfileManager.calculate",
        lambda self: expected,)
    profile = StepProfile(
        step_name=StepName.DISTANCE_PROFILE,
        distribution=DIST_DISTANCE_PROFILE,
        input_artifact=ARTI_IMG,
        output_artifact=ARTI_DIST_PROF,
        output_name=DISTANCE_PROFILE_NAME,)

    result = run_distance_profile(
        DistanceProfileSettings(),
        state,
        profile,)[0]

    output_path = tmp_path / DISTANCE_PROFILE_NAME
    assert result.artifact(ARTI_DIST_PROF) == output_path
    assert StepName.DISTANCE_PROFILE in result.completed_steps
    pd.testing.assert_frame_equal(pd.read_parquet(output_path), expected)
    from fisch.environment.paths import experiment_state_path
    assert experiment_state_path(tmp_path).is_file()
