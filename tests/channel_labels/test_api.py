from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest
import tifffile
from typer.testing import CliRunner

from fits.channel_labels import apply_labels, files_to_update, inspect_run
from fits.channel_labels.lock import run_write_guard
from fits.cli.main import app
from fits_io import FitsIO


def _run(tmp_path):
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    source = experiment / "input.tif"
    raw = np.arange(2 * 2 * 8 * 9, dtype=np.uint16).reshape(2, 2, 8, 9)
    tifffile.imwrite(source, raw, imagej=True, metadata={"axes": "TCYX"})
    array_path = FitsIO.from_path(source).save_array(
        raw, channel_labels=["GFP", "RFP"],
        output_path=experiment / "fits_array.tif", compression="none",
        custom_metadata={"tracking_viewer_display": {
            "raw_image_channel": "GFP", "mask_channel": "RFP"}},
        imagej_overlays=[b"track ROI", b"mask ROI"])
    FitsIO.from_path(array_path).save_array(
        raw[:, 1], export_channels=["RFP"],
        output_path=experiment / "fits_mask.tif")
    settings = tmp_path / ".fits" / "fits_settings.toml"
    settings.parent.mkdir()
    settings.write_text('''[convert.params]
channel_labels = ["GFP", "RFP"] # keep me
export_channels = ["RFP"]
[track.params]
channel_to_track = ["RFP"]
''')
    table = pd.DataFrame({
        "experiment_id": ["experiment"], "cell_id": ["old"],
        "object_name": ["tracking"], "object_channel": ["RFP"],
        "intensity_channel": ["GFP"], "label": [1], "frame": [0]})
    table.to_parquet(experiment / "fits_quantification.parquet", index=False)
    return raw, array_path, settings


def test_run_rename_preserves_pixels_overlay_indices_and_updates_references(tmp_path):
    raw, array_path, settings = _run(tmp_path)
    plan = inspect_run(tmp_path)
    assert dict(plan.labels) == {0: "GFP", 1: "RFP"}
    changed = apply_labels(plan, {0: "Green", 1: "Red"})
    assert len(changed) == 4
    with tifffile.TiffFile(array_path) as tif:
        np.testing.assert_array_equal(tif.asarray(), raw)
        imagej_metadata = tif.imagej_metadata
        assert imagej_metadata is not None
        assert imagej_metadata["Overlays"] == [b"track ROI", b"mask ROI"]
        assert tif.series[0].axes == "TCYX"
    renamed = FitsIO.from_path(array_path)
    assert renamed.channel_labels == ["Green", "Red"]
    assert renamed.source_channel_indices == [0, 1]
    assert renamed.artifact_channel_indices == [0, 1]
    assert renamed.metadata.custom_metadata["tracking_viewer_display"] == {
        "raw_image_channel": "Green", "mask_channel": "Red"}
    subset = FitsIO.from_path(array_path.with_name("fits_mask.tif"))
    assert subset.channel_labels == ["Red"]
    assert subset.artifact_channel_indices == [1]
    assert 'channel_to_track = ["Red"]' in settings.read_text()
    assert "# keep me" in settings.read_text()
    table = pd.read_parquet(array_path.with_name("fits_quantification.parquet"))
    assert table.loc[0, "object_channel"] == "Red"
    assert table.loc[0, "intensity_channel"] == "Green"
    assert "|channel=Red|" in table.loc[0, "cell_id"]


def test_scan_rejects_conflicting_index_labels(tmp_path):
    _, array_path, _ = _run(tmp_path)
    subset = FitsIO.from_path(array_path.with_name("fits_mask.tif"))
    subset.set_channel_labels(["Wrong"])
    with pytest.raises(ValueError, match="Channel 1"):
        inspect_run(tmp_path)


def test_apply_rejects_stale_inspection(tmp_path):
    _, _, settings = _run(tmp_path)
    plan = inspect_run(tmp_path)
    settings.write_text(settings.read_text() + "\n# later\n")
    with pytest.raises(RuntimeError, match="changed since inspection"):
        apply_labels(plan, {0: "Green", 1: "Red"})


def test_scan_rejects_conflicting_saved_settings(tmp_path):
    _, _, settings = _run(tmp_path)
    settings.write_text(settings.read_text().replace('"GFP", "RFP"', '"RFP", "GFP"'))
    with pytest.raises(ValueError, match="Source channel 0"):
        inspect_run(tmp_path)


def test_failed_table_update_restores_earlier_tiffs(tmp_path, monkeypatch):
    _, array_path, _ = _run(tmp_path)
    plan = inspect_run(tmp_path)

    def fail(*_args):
        raise OSError("table unavailable")

    monkeypatch.setattr("fits.channel_labels.apply.rename_table", fail)
    with pytest.raises(RuntimeError, match="table unavailable"):
        apply_labels(plan, {0: "Green", 1: "Red"})
    assert FitsIO.from_path(array_path).channel_labels == ["GFP", "RFP"]
    assert FitsIO.from_path(array_path.with_name("fits_mask.tif")).channel_labels == ["RFP"]


def test_inspection_refuses_active_run_writer(tmp_path):
    _run(tmp_path)
    with run_write_guard(tmp_path):
        with pytest.raises(RuntimeError, match="already active"):
            inspect_run(tmp_path)


def test_state_and_distance_table_references_follow_renamed_channels(tmp_path):
    _, array_path, _ = _run(tmp_path)
    state_path = array_path.with_name("experiment_state.json")
    state_path.write_text(json.dumps({
        "meta": {"steps": {"segment": {
            "params": {"reference_channel": "GFP"},
            "channels": {"1": {"channel": 1, "channel_label": "RFP"}},
        }}}}))
    distance_path = array_path.with_name("fits_distance_profile.parquet")
    pd.DataFrame({"channel": ["GFP"], "ref_channel": ["RFP"],
                  "roi_channel": [None], "distance": [2.5]}).to_parquet(distance_path)
    apply_labels(inspect_run(tmp_path), {0: "Green", 1: "Red"})
    state = json.loads(state_path.read_text())
    assert state["meta"]["steps"]["segment"]["params"]["reference_channel"] == "Green"
    assert state["meta"]["steps"]["segment"]["channels"]["1"] == {
        "channel": 1, "channel_label": "Red"}
    distance = pd.read_parquet(distance_path)
    assert distance.loc[0, "channel"] == "Green"
    assert distance.loc[0, "ref_channel"] == "Red"
    assert pd.isna(distance.loc[0, "roi_channel"])
    assert distance.loc[0, "distance"] == 2.5


def test_cli_preview_requires_apply_before_writing(tmp_path):
    _, array_path, _ = _run(tmp_path)
    runner = CliRunner()
    preview = runner.invoke(app, ["channel-labels", str(tmp_path), "--set", "1=Red"])
    assert preview.exit_code == 0
    assert "Preview only" in preview.output
    assert FitsIO.from_path(array_path).channel_labels == ["GFP", "RFP"]
    result = runner.invoke(app, ["channel-labels", str(tmp_path), "--set", "1=Red", "--apply"])
    assert result.exit_code == 0
    assert FitsIO.from_path(array_path).channel_labels == ["GFP", "Red"]


def test_only_files_referencing_changed_channel_are_written(tmp_path):
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    source = experiment / "input.tif"
    raw = np.zeros((2, 3, 8, 9), dtype=np.uint16)
    tifffile.imwrite(source, raw, imagej=True, metadata={"axes": "TCYX"})
    array_path = FitsIO.from_path(source).save_array(
        raw, channel_labels=["BFP", "GFP", "RFP"],
        output_path=experiment / "fits_array.tif")
    mask_path = FitsIO.from_path(array_path).save_array(
        raw[:, 2], export_channels=["RFP"],
        output_path=experiment / "fits_mask.tif")
    table_path = experiment / "fits_quantification.parquet"
    pd.DataFrame({"experiment_id": ["experiment"], "cell_id": ["old"],
                  "object_name": ["tracking"], "object_channel": ["RFP"],
                  "intensity_channel": ["GFP"], "label": [1], "frame": [0],
                  "area": [17]}).to_parquet(table_path, index=False)
    state_path = experiment / "experiment_state.json"
    state_path.write_text(json.dumps({"meta": {"steps": {"track": {
        "channels": {"2": {"channel": 2, "channel_label": "RFP"}}}}}}))
    settings_path = tmp_path / ".fits" / "fits_settings.toml"
    settings_path.parent.mkdir()
    settings_path.write_text('[convert.params]\nchannel_labels = ["BFP", "GFP", "RFP"]\n')

    plan = inspect_run(tmp_path)
    present = dict(plan.file_labels)
    assert files_to_update(plan, dict(plan.labels)) == ()
    assert apply_labels(plan, dict(plan.labels)) == ()
    assert "BFP" in present[array_path]
    assert all("BFP" not in present[path] for path in (mask_path, table_path, state_path))
    proposed = {0: "Blue", 1: "GFP", 2: "RFP"}
    assert files_to_update(plan, proposed) == (array_path, settings_path)
    preview = CliRunner().invoke(app, ["channel-labels", str(tmp_path), "--set", "0=Blue"])
    assert preview.exit_code == 0
    assert "experiment/fits_array.tif" in preview.output
    assert ".fits/fits_settings.toml" in preview.output
    assert "fits_mask.tif" not in preview.output
    assert "fits_quantification.parquet" not in preview.output
    assert "experiment_state.json" not in preview.output
    untouched = {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
                 for path in (mask_path, table_path, state_path)}
    progress = []
    assert apply_labels(plan, proposed, lambda done, total, path: progress.append(
        (done, total, path))) == (array_path, settings_path)
    assert progress == [(1, 2, array_path), (2, 2, settings_path)]
    for path, before in untouched.items():
        assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == before
    assert FitsIO.from_path(array_path).channel_labels == ["Blue", "GFP", "RFP"]
    assert FitsIO.from_path(mask_path).channel_labels == ["RFP"]
    assert '"Blue", "GFP", "RFP"' in settings_path.read_text()


def test_tiff_with_only_metadata_reference_is_updated(tmp_path):
    _, array_path, _ = _run(tmp_path)
    mask_path = array_path.with_name("fits_mask.tif")
    FitsIO.from_path(mask_path).set_channel_labels(
        ["RFP"], custom_metadata={"tracking_viewer_display": {
            "raw_image_channel": "GFP"}})
    plan = inspect_run(tmp_path)
    assert mask_path in files_to_update(plan, {0: "Green", 1: "RFP"})
    changed = apply_labels(plan, {0: "Green", 1: "RFP"})
    assert mask_path in changed
    reader = FitsIO.from_path(mask_path)
    assert reader.channel_labels == ["RFP"]
    assert reader.metadata.custom_metadata["tracking_viewer_display"]["raw_image_channel"] == "Green"


def test_intensity_only_rename_keeps_cell_identity(tmp_path):
    _, array_path, _ = _run(tmp_path)
    table_path = array_path.with_name("fits_quantification.parquet")
    plan = inspect_run(tmp_path)
    apply_labels(plan, {0: "Green", 1: "RFP"})
    table = pd.read_parquet(table_path)
    assert table.loc[0, "intensity_channel"] == "Green"
    assert table.loc[0, "object_channel"] == "RFP"
    assert table.loc[0, "cell_id"] == "old"
