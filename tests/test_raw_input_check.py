"""Shared raw-input checks and conversion folder planning."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tifffile import imwrite

from fits.environment.constant import WORKFLOW_ORDER, StepName
from fits.environment.paths import EXPERIMENT_DIR_NAME
from fits.gui.settings import SettingsAdapter
from fits.pipeline import start_pipeline
from fits.workflows.checks.raw_inputs import inspect_raw_inputs
from fits.workflows.experiments.acquisitions import group_acquisition
from fits.workflows.experiments import discover_saved_states


def _write_tiff(path: Path, channels: int = 2) -> None:
    """
    Write a small acquisition with explicit channel metadata.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    imwrite(path, np.zeros((channels, 8, 8), dtype=np.uint16), imagej=True, metadata={"axes": "CYX"})


def _settings(run_dir: Path, execution: str = "conveyor") -> Path:
    """
    Save a conversion-only configuration outside the run's raw-input directory.
    """
    adapter = SettingsAdapter()
    adapter.run_dir = str(run_dir)
    adapter.user_name = "Test"
    adapter.set_runtime_value("execution", execution)
    for step in WORKFLOW_ORDER:
        adapter.set_step_enabled(step, step == StepName.CONVERT)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["Green", "Red"])
    return adapter.save(run_dir.parent / "settings.toml")


def test_channel_mismatch_reports_every_input_without_changes(tmp_path: Path) -> None:
    """
    Identify incompatible acquisitions across subfolders using relative paths and counts.
    """
    first = tmp_path / "control" / "sample.tif"
    second = tmp_path / "treated" / "sample.tiff"
    _write_tiff(first, 1)
    _write_tiff(second, 3)
    before = {path: path.read_bytes() for path in (first, second)}
    report = inspect_raw_inputs(tmp_path)
    assert report.channel_counts == {first: 1, second: 3}
    assert "control/sample.tif: 1 channel" in report.describe()
    assert "treated/sample.tiff: 3 channels" in report.describe()
    assert "separate run directories" in report.describe()
    assert {path: path.read_bytes() for path in before} == before
    assert not (first.parent / "sample").exists()


def test_duplicate_stems_only_change_planned_folders_in_same_parent(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch,
                                                                  ) -> None:
    """
    Use extension suffixes only for same-folder collisions, including mixed ND2/TIFF inputs.
    """
    files = [tmp_path / "same" / "sample.nd2", tmp_path / "same" / "sample.tif",
             tmp_path / "other" / "sample.nd2", tmp_path / "third" / "sample.tif"]
    for path in files:
        path.parent.mkdir(exist_ok=True)
        path.touch()
    monkeypatch.setattr("fits.workflows.checks.raw_inputs.FitsIO.from_path",
                        lambda path: SimpleNamespace(reader=SimpleNamespace(channel_count=2)))
    report = inspect_raw_inputs(tmp_path)
    assert not report.problems
    assert report.acquisition_directories == {
        files[0]: files[0].parent / "sample_nd2", files[1]: files[1].parent / "sample_tif",
        files[2]: files[2].parent / "sample", files[3]: files[3].parent / "sample"}
    assert all(path.is_file() for path in files)
    assert not list(tmp_path.rglob(EXPERIMENT_DIR_NAME))


@pytest.mark.parametrize("existing", [True, False])
def test_unresolved_acquisition_destinations_are_blocking(tmp_path: Path, existing: bool) -> None:
    """
    Refuse existing destinations and collisions introduced by extension-based folder names.
    """
    _write_tiff(tmp_path / "sample.tif")
    if existing:
        (tmp_path / "sample").mkdir()
    else:
        _write_tiff(tmp_path / "sample.tiff")
        _write_tiff(tmp_path / "sample_tif.tif")
    report = inspect_raw_inputs(tmp_path)
    assert "Cannot create acquisition folder" in report.describe()
    assert "sample.tif" in report.describe()
    assert (tmp_path / "sample.tif").is_file()


def test_unreadable_metadata_blocks_instead_of_guessing(tmp_path: Path) -> None:
    """
    Surface metadata failures with the affected acquisition path.
    """
    (tmp_path / "broken.nd2").write_bytes(b"invalid")
    report = inspect_raw_inputs(tmp_path)
    assert not report.channel_counts
    assert "Cannot read raw input metadata: broken.nd2" in report.describe()


def test_explicit_labels_match_source_channels_and_empty_labels_use_defaults(tmp_path: Path) -> None:
    """
    Check source counts without mistaking a selected export subset for all inputs.
    """
    _write_tiff(tmp_path / "sample.tif", 2)
    defaults = inspect_raw_inputs(tmp_path, channel_labels=[])
    assert not defaults.problems
    assert not defaults.warnings
    assert not inspect_raw_inputs(tmp_path, channel_labels=["Green", "Red"]).problems
    report = inspect_raw_inputs(tmp_path, channel_labels=["Green", "Red", "Blue"])
    assert not report.problems
    assert len(report.warnings) == 1
    assert "Expected 2 channels, got 3 channel labels" in report.warnings[0]
    assert "default names: C_1, C_2." in report.warnings[0]


def test_pipeline_warns_and_uses_defaults_for_label_count_mismatch(tmp_path: Path) -> None:
    """
    Convert with the exact default labels and log the mismatch instead of rejecting the run.
    """
    run = tmp_path / "run"
    _write_tiff(run / "input.tif", 3)
    settings = _settings(run)
    from fits_io import FitsIO

    start_pipeline(settings_path=settings, convert_only=True, terminal_progress=False)
    output = next(run.rglob("fits_array_raw.tif"))
    assert FitsIO.from_path(output).channel_labels == ["C_1", "C_2", "C_3"]
    log = next((run / ".fits" / "logs").glob("*.log")).read_text()
    assert "Expected 3 channels, got 2 channel labels" in log
    assert "default names: C_1, C_2, C_3." in log


def test_pipeline_empty_labels_uses_reader_defaults(tmp_path: Path) -> None:
    """
    Convert unnamed source channels without requiring user-defined labels.
    """
    from fits_io import FitsIO

    run = tmp_path / "run"
    _write_tiff(run / "input.tif", 2)
    adapter = SettingsAdapter()
    adapter.run_dir = str(run)
    adapter.user_name = "Test"
    settings = adapter.save(tmp_path / "settings.toml")
    start_pipeline(settings_path=settings, convert_only=True, terminal_progress=False)
    output = next(run.rglob("fits_array_raw.tif"))
    assert FitsIO.from_path(output).channel_labels == ["C_1", "C_2"]


def test_duplicates_inside_existing_acquisition_require_resolution(tmp_path: Path) -> None:
    """
    Preserve existing acquisition paths instead of allowing two originals to overwrite the same series.
    """
    (tmp_path / EXPERIMENT_DIR_NAME).mkdir()
    _write_tiff(tmp_path / "sample.tif")
    _write_tiff(tmp_path / "sample.tiff")
    report = inspect_raw_inputs(tmp_path)
    assert not report.acquisition_directories
    assert "Duplicate stem 'sample' inside existing acquisition folder" in report.describe()
    assert "sample.tif" in report.describe()
    assert "sample.tiff" in report.describe()


def test_grouping_logs_folder_adjustment_and_preserves_filename(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """
    Log automatic folder adjustment once without altering acquisition bytes or basename.
    """
    source = tmp_path / "sample.tif"
    _write_tiff(source)
    before = source.read_bytes()
    target = tmp_path / "sample_tif"
    with caplog.at_level("INFO", logger="fits.workflows.experiments.acquisitions"):
        moved = group_acquisition(source, target)
        assert group_acquisition(moved) == moved
    assert moved == target / "sample.tif"
    assert moved.read_bytes() == before
    assert sum("Duplicate acquisition stem" in record.message for record in caplog.records) == 1


def test_pipeline_rejects_mixed_channels_before_moving_or_writing(tmp_path: Path) -> None:
    """
    Enforce the shared channel-count rule through the pipeline entry point.
    """
    run_dir = tmp_path / "run"
    _write_tiff(run_dir / "one.tif", 1)
    _write_tiff(run_dir / "two.tiff", 2)
    settings = _settings(run_dir)
    with pytest.raises(ValueError, match="different numbers of channels"):
        start_pipeline(settings_path=settings, convert_only=True, terminal_progress=False)
    assert sorted(path.name for path in run_dir.iterdir()) == ["one.tif", "two.tiff"]


@pytest.mark.parametrize("convert_only,execution", [(True, "conveyor"), (False, "batch"), (False, "conveyor")])
def test_pipeline_converts_duplicate_stems_and_reopens_grouped_inputs(tmp_path: Path,
                                                                    convert_only: bool,
                                                                    execution: str,
                                                                    ) -> None:
    """
    Convert same-stem TIFF formats into separate acquisition folders and reuse saved paths on rerun.
    """
    run_dir = tmp_path / "run"
    originals = [run_dir / "sample.tif", run_dir / "sample.tiff"]
    for path in originals:
        _write_tiff(path)
    before = {path.name: path.read_bytes() for path in originals}
    settings = _settings(run_dir, execution)
    start_pipeline(settings_path=settings, convert_only=convert_only, terminal_progress=False)
    for extension in ("tif", "tiff"):
        acquisition = run_dir / f"sample_{extension}"
        assert (acquisition / f"sample.{extension}").read_bytes() == before[f"sample.{extension}"]
        assert (acquisition / "sample_s1" / "fits_array_raw.tif").is_file()
    report = inspect_raw_inputs(run_dir)
    assert not report.problems
    assert not report.acquisition_directories
    start_pipeline(settings_path=settings, convert_only=convert_only, terminal_progress=False)
    states = discover_saved_states(run_dir)
    assert len(states) == 2
    assert {state.original_image for state in states} == {
        run_dir / "sample_tif" / "sample.tif", run_dir / "sample_tiff" / "sample.tiff"}
    assert all(state.acquisition_directory is None for state in states)
