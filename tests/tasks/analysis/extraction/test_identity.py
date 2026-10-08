"""Cell identity across time, measurements, and portable experiment folders."""

from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest
from bioimagequant import ExtractData

from fits.environment.constant import (
    ARTI_IMG, ARTI_QUANTI, ARTI_SEG, ARTI_TRACK, DIST_EXTRACT,
    FITS_QUANTI_NAME, StepName,
)
from fits.settings.models import ExtractSettings
from fits.tasks.analysis.extraction.aggregate import _save_master_quantification
from fits.tasks.analysis.extraction.extract import extract
from fits.tasks.analysis.extraction.manager import ExtractionManager
from fits.tasks.analysis.identity import add_quantification_ids
from fits.workflows.definitions.models import StepProfile
from fits.workflows.experiments import (
    ExperimentState, assemble_experiment_states, discover_saved_states,
    save_experiment_state,
)


def measurements() -> pd.DataFrame:
    """Two intensity channels and two frames for the same object label."""
    return pd.DataFrame({
        "object_name": [ARTI_TRACK] * 4,
        "object_channel": ["iRed"] * 4,
        "label": [24] * 4,
        "frame": [1, 1, 2, 2],
        "intensity_channel": ["GFP", "RFP"] * 2,
    })


def test_tracking_identity_is_shared_across_frames_and_intensity_channels() -> None:
    source = measurements()
    result = add_quantification_ids(source, "run/parent/sample_s1")
    assert result["cell_id"].nunique() == 1
    assert result["cell_id"].iloc[0] == (
        "run/parent/sample_s1|object=tracking|channel=iRed|label=24")
    pd.testing.assert_frame_equal(result[source.columns], source)
    assert "cell_id" not in source


def test_segmentation_identity_is_per_frame_and_distinct_from_tracks() -> None:
    source = measurements()
    source["object_name"] = ARTI_SEG
    result = add_quantification_ids(source, "run/sample_s1")
    assert result["cell_id"].nunique() == 2
    assert result["cell_id"].iloc[0].endswith("|frame=1")
    assert result["cell_id"].iloc[2].endswith("|frame=2")
    assert not set(result["cell_id"]) & set(
        add_quantification_ids(measurements(), "run/sample_s1")["cell_id"])


def test_identity_distinguishes_channels_parents_and_escaped_delimiters() -> None:
    source = measurements()
    source["object_channel"] = [None, "", "iRed|label=24", "iRed%7Clabel%3D24"]
    first = add_quantification_ids(source, "run/parent_a/sample_s1")
    second = add_quantification_ids(source, "run/parent_b/sample_s1")
    assert first["cell_id"].nunique() == 4
    assert not set(first["cell_id"]) & set(second["cell_id"])


def test_invalid_segmentation_identity_fails_instead_of_merging_frames() -> None:
    source = measurements().drop(columns="frame")
    source["object_name"] = ARTI_SEG
    with pytest.raises(ValueError, match="frame numbers"):
        add_quantification_ids(source, "run/sample")
    source["frame"] = [1, None, 2, 2]
    with pytest.raises(ValueError, match="frame numbers"):
        add_quantification_ids(source, "run/sample")


def test_empty_measurements_and_repeated_identity_assignment() -> None:
    empty = add_quantification_ids(pd.DataFrame(), "run/sample")
    assert list(empty.columns) == ["experiment_id", "cell_id"]
    assert empty.empty
    first = add_quantification_ids(measurements(), "old/sample")
    second = add_quantification_ids(first, "new/sample")
    pd.testing.assert_frame_equal(
        second, add_quantification_ids(measurements(), "new/sample"))


def test_discovery_rebinds_run_root_after_moving_entire_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "old_parent" / "run"
    workdir = run_dir / "condition" / "sample_s1"
    workdir.mkdir(parents=True)
    state = ExperimentState.init(workdir, workdir.parent / "sample.nd2", run_dir=run_dir)
    save_experiment_state(state)
    moved = tmp_path / "new_parent" / "run"
    moved.parent.mkdir()
    shutil.move(str(run_dir), str(moved))
    restored = discover_saved_states(moved)[0]
    assert restored.run_dir == moved
    assert restored.analysis_experiment_id == state.analysis_experiment_id == "run/condition/sample_s1"
    assert str(tmp_path) not in restored.analysis_experiment_id
    assert "run_dir" not in (restored.workdir / "experiment_state.json").read_text()


def test_assembly_preserves_root_when_conversion_creates_branch(tmp_path: Path) -> None:
    raw = tmp_path / "condition" / "sample.nd2"
    raw.parent.mkdir()
    raw.touch()
    state = assemble_experiment_states(tmp_path, [raw], {}, "tester")[0]
    branch_dir = raw.parent / "sample_s1"
    branch = state.with_complete_step(
        step_name=StepName.CONVERT, artifact_kind=ARTI_IMG,
        artifact_path=branch_dir / "fits_array.tif", workdir=branch_dir)
    assert branch.analysis_experiment_id == f"{tmp_path.name}/condition/sample_s1"


def test_master_upgrades_legacy_ids_without_rewriting_experiment_files(tmp_path: Path) -> None:
    states: list[ExperimentState] = []
    originals: list[tuple[Path, bytes]] = []
    for parent in ("control", "treated"):
        workdir = tmp_path / parent / "sample_s1"
        workdir.mkdir(parents=True)
        path = workdir / FITS_QUANTI_NAME
        source = measurements()
        source.insert(0, "experiment_id", str(workdir))
        source.to_parquet(path, index=False)
        originals.append((path, path.read_bytes()))
        states.append(ExperimentState.init(workdir, workdir.parent / "sample.nd2").with_complete_step(
            step_name=StepName.EXTRACT, artifact_kind=ARTI_QUANTI, artifact_path=path))
    master_path = _save_master_quantification(states, tmp_path)
    assert master_path is not None
    master = pd.read_parquet(master_path)
    assert master["experiment_id"].tolist() == (
        [f"{tmp_path.name}/control/sample_s1"] * 4
        + [f"{tmp_path.name}/treated/sample_s1"] * 4)
    assert master["cell_id"].nunique() == 2
    assert master["track_length"].tolist() == [2] * 8
    assert master["track_start_frame"].tolist() == [1] * 8
    assert master["track_end_frame"].tolist() == [2] * 8
    for path, original in originals:
        assert path.read_bytes() == original


@pytest.mark.parametrize("object_name", [ARTI_TRACK, ARTI_SEG])
def test_extraction_saves_portable_ids_with_real_quantification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, object_name: str,
) -> None:
    workdir = tmp_path / "condition" / "sample_s1"
    workdir.mkdir(parents=True)
    image_path = workdir / "fits_array.tif"
    image_path.touch()
    state = ExperimentState.init(workdir, workdir.parent / "sample.nd2", run_dir=tmp_path)
    state = state.with_complete_step(
        step_name=StepName.CONVERT, artifact_kind=ARTI_IMG, artifact_path=image_path)
    extractor = ExtractData()
    extractor.add_intensity(np.ones((4, 4, 4)), "TYX", channel_labels=["GFP"])
    labels = np.zeros((4, 4, 4), dtype=np.uint16)
    labels[[0, 3], 1:3, 1:3] = 24
    extractor.add_labels(labels, "TYX", name=object_name, channel_labels=["iRed"])
    monkeypatch.setattr(ExtractionManager, "prepare_quantification", lambda self: extractor)
    profile = StepProfile(
        step_name=StepName.EXTRACT, distribution=DIST_EXTRACT,
        input_artifact=ARTI_IMG, output_artifact=ARTI_QUANTI,
        output_name=FITS_QUANTI_NAME)
    updated = extract(ExtractSettings(), state, profile)[0]
    path = updated.artifact(ARTI_QUANTI)
    assert path is not None
    table = pd.read_parquet(path)
    assert table["experiment_id"].unique().tolist() == [f"{tmp_path.name}/condition/sample_s1"]
    assert table["cell_id"].nunique() == (1 if object_name == ARTI_TRACK else 2)
    if object_name == ARTI_TRACK:
        assert table["track_length"].tolist() == [4, 4]
        assert table["track_start_frame"].tolist() == [1, 1]
        assert table["track_end_frame"].tolist() == [4, 4]
    else:
        assert table[["track_length", "track_start_frame", "track_end_frame"]].isna().to_numpy().all()
