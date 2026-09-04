from pathlib import Path

import pandas as pd

from fits.environment.constant import ARTI_DIST_PROF, StepName
from fits.environment.state import ExperimentState
from fits.tasks.analysis.aggregate import save_master_analysis_table


def test_master_distance_profile_retains_condition_tags(tmp_path: Path) -> None:
    condition_dir = tmp_path / "Treated" / "Dose 1"
    workdir = condition_dir / "sample_s1"
    workdir.mkdir(parents=True)
    raw_path = condition_dir / "sample.nd2"
    profile_path = workdir / "fits_distance_profile.parquet"
    pd.DataFrame({
        "experiment_id": ["sample"],
        "frame": [1],
        "dist_px": [2.5],
        "mean_intensity": [42.0],
    }).to_parquet(profile_path, index=False)

    state = ExperimentState.init(condition_dir, raw_path).with_complete_step(
        step_name=StepName.DISTANCE_PROFILE,
        artifact_kind=ARTI_DIST_PROF,
        artifact_path=profile_path,
        workdir=workdir,)

    result = save_master_analysis_table(
        [state],
        tmp_path,
        artifact_kind=ARTI_DIST_PROF,
        output_name="master_distance_profile.parquet",)

    assert result == tmp_path / "master_distance_profile.parquet"
    master = pd.read_parquet(result)
    assert master.loc[0, "condition_level_1"] == "Treated"
    assert master.loc[0, "condition_level_2"] == "Dose 1"
