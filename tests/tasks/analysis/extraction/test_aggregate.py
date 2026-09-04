from pathlib import Path

import pandas as pd

from fits.environment.constant import ARTI_QUANTI, StepName
from fits.environment.state import ExperimentState
from fits.tasks.analysis.extraction.aggregate import _save_master_quantification


def _state_with_quantification(
    run_dir: Path,
    condition_parts: tuple[str, ...],
    experiment_name: str,
    value: int,
) -> ExperimentState:
    condition_dir = run_dir.joinpath(*condition_parts)
    raw_path = condition_dir / f"{experiment_name}.nd2"
    workdir = condition_dir / f"{experiment_name}_s1"
    workdir.mkdir(parents=True)

    quantification_path = workdir / "fits_quantification.parquet"
    pd.DataFrame(
        {
            "experiment_id": [experiment_name],
            "measurement": [value],
        }
    ).to_parquet(quantification_path, index=False)

    state = ExperimentState.init(
        workdir=condition_dir,
        original_image=raw_path,
    )
    return state.with_complete_step(
        step_name=StepName.EXTRACT,
        artifact_kind=ARTI_QUANTI,
        artifact_path=quantification_path,
        workdir=workdir,
    )


def test_master_quantification_adds_nested_condition_levels(tmp_path: Path) -> None:
    control = _state_with_quantification(
        tmp_path,
        ("Control", "Ligand A"),
        "control_a",
        1,
    )
    treated = _state_with_quantification(
        tmp_path,
        ("Treated",),
        "treated",
        2,
    )

    master_path = _save_master_quantification(
        [control, treated],
        tmp_path,
    )

    assert master_path == tmp_path / "master_quantification.parquet"
    master = pd.read_parquet(master_path)
    assert list(master.columns[:3]) == [
        "experiment_id",
        "condition_level_1",
        "condition_level_2",
    ]
    assert master.loc[0, "condition_level_1"] == "Control"
    assert master.loc[0, "condition_level_2"] == "Ligand A"
    assert master.loc[1, "condition_level_1"] == "Treated"
    assert pd.isna(master.loc[1, "condition_level_2"])


def test_master_quantification_is_not_created_without_artifacts(tmp_path: Path) -> None:
    state = ExperimentState.init(
        workdir=tmp_path,
        original_image=tmp_path / "image.nd2",
    )

    master_path = _save_master_quantification([state], tmp_path)

    assert master_path is None
    assert not (tmp_path / "master_quantification.parquet").exists()
