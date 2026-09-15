from datetime import datetime
from pathlib import Path

import pytest

from fits.environment.constant import StepName
from fits.workflows.experiments import (
    ExperimentState, load_experiment_state, save_experiment_state)


def test_save_and_load_state_roundtrip(tmp_path: Path) -> None:
    image = tmp_path / "fits_array.tif"
    image.touch()
    state = ExperimentState.init(tmp_path, tmp_path / "a.nd2").with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind="image",
        artifact_path=image,
    )

    assert save_experiment_state(state) is state
    loaded = load_experiment_state(tmp_path)

    assert loaded == state
    assert isinstance(loaded.artifacts["raw_image"], Path)
    assert isinstance(loaded.updated_at, datetime)


def test_load_state_raises_on_invalid_artifact_path_type(tmp_path: Path) -> None:
    (tmp_path / "experiment_state.json").write_text(
        '{"artifacts": {"raw_image": 10}, "completed_steps": [], '
        '"updated_at": null, "meta": {}}',
        encoding="utf-8",
    )

    with pytest.raises(
        TypeError,
        match=r"artifacts\['raw_image'\] must be a string path",
    ):
        load_experiment_state(tmp_path)


def test_save_state_cleans_temporary_file_when_replace_fails(
    monkeypatch, tmp_path: Path,
) -> None:
    state = ExperimentState.init(tmp_path, tmp_path / "a.nd2")

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(
        "fits.workflows.experiments.persistence.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        save_experiment_state(state)

    assert list(tmp_path.glob(".experiment_state.json.*.tmp")) == []
    assert not (tmp_path / "experiment_state.json").exists()
