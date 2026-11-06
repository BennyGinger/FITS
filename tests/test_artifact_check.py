from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fits_io import FitsIO
import tifffile

from fits.environment import constant as cst
from fits.gui.settings import SettingsAdapter
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.decisions import apply_decision
from fits.workflows.checks.models import ArtifactRecord, PreflightReport
from fits.settings.resolution import apply_overwrite_cascade
from fits.workflows.experiments import ExperimentState, save_experiment_state


@pytest.mark.parametrize("selected,other,same_experiment,exists,review", [
    (cst.StepName.BG_SUB, cst.StepName.SEGMENT, True, False, False),
    (cst.StepName.BG_SUB, cst.StepName.SEGMENT, True, True, True),
    (cst.StepName.BG_SUB, cst.StepName.SEGMENT, False, True, False),
    (cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE, True, True, False),
    (cst.StepName.DISTANCE_PROFILE, cst.StepName.EXTRACT, True, True, False),
])
def test_overwrite_review_requires_existing_downstream_results(tmp_path: Path,
                                                              selected: cst.StepName,
                                                              other: cst.StepName,
                                                              same_experiment: bool,
                                                              exists: bool,
                                                              review: bool,
                                                              ) -> None:
    """
    Review saved dependents, excluding future files, other experiments and sibling analyses.
    """
    source = tmp_path / "selected" / "output.tif"
    source.parent.mkdir()
    source.touch()
    dependent = (source.parent if same_experiment else tmp_path / "other") / "dependent.tif"
    if exists:
        dependent.parent.mkdir(exist_ok=True)
        dependent.touch()
    records = (ArtifactRecord(source, selected, None), ArtifactRecord(dependent, other, None))
    report = PreflightReport(records, (selected,), (other,) if selected == cst.StepName.BG_SUB else (), ())
    assert report.needs_decision is review


@pytest.mark.parametrize("step,review", [(cst.StepName.REGISTER_TIME, True), (cst.StepName.BG_SUB, False)])
def test_overwrite_review_preserves_drawing_geometry_dependencies(tmp_path: Path,
                                                                 step: cst.StepName,
                                                                 review: bool,
                                                                 ) -> None:
    """
    Review geometry changes affecting drawings while permitting intensity-only reruns.
    """
    image = tmp_path / "image.tif"
    drawing = tmp_path / "fits_ref_edge.tif"
    image.touch()
    drawing.touch()
    report = PreflightReport((ArtifactRecord(image, step, None), ArtifactRecord(drawing, None, None)),
                             (step,), (), ())
    assert report.needs_decision is review


def test_overwriting_an_analysis_does_not_overwrite_its_sibling() -> None:
    """
    Keep Quantification independent when rerunning Distance Profile.
    """
    config = {str(step): {"enabled": True, "params": {"overwrite": step == cst.StepName.DISTANCE_PROFILE}}
              for step in (cst.StepName.DISTANCE_PROFILE, cst.StepName.EXTRACT)}
    resolved = apply_overwrite_cascade(config, cst.WORKFLOW_ORDER)
    assert resolved[cst.StepName.DISTANCE_PROFILE]["params"]["overwrite"]
    assert not resolved[cst.StepName.EXTRACT]["params"]["overwrite"]


def test_converted_run_with_unfinished_pipeline_has_no_artifact_conflicts(tmp_path: Path) -> None:
    """
    Treat missing future outputs as new work while detecting lost completed outputs.
    """
    source = tmp_path / "acquisition.tif"
    pixels = np.zeros((8, 8), dtype=np.uint16)
    tifffile.imwrite(source, pixels, photometric="minisblack", metadata={"axes": "YX"})
    reader = FitsIO.from_path(source)
    output = tmp_path / cst.FITS_ARRAY_RAW
    payload = reader.build_payload(export_channels="all", artifact_type=cst.ARTI_IMG_RAW,
                                   custom_metadata={"pipeline_meta": {"version": "4.0.0"}}).new_revision(
                                       [{"artifact_path": source.name, "external": True, "created_at": None}])
    reader.save_array(pixels, metadata=payload, output_path=output)
    state = ExperimentState.init(tmp_path, source).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=output)
    save_experiment_state(state)
    adapter = SettingsAdapter()
    for step in cst.WORKFLOW_ORDER:
        adapter.set_step_enabled(step, step in (cst.StepName.CONVERT, cst.StepName.BG_SUB,
                                              cst.StepName.SEGMENT, cst.StepName.TRACK, cst.StepName.EXTRACT))
    config = adapter.as_mapping()
    report = inspect_run(tmp_path, config)
    assert not report.conflicts
    assert not report.needs_decision

    missing = tmp_path / cst.FITS_MASK_SEG
    state = state.with_complete_step(step_name=cst.StepName.SEGMENT,
                                    artifact_kind=cst.ARTI_SEG, artifact_path=missing)
    save_experiment_state(state)
    report = inspect_run(tmp_path, config)
    assert any(record.path == missing for record in report.conflicts)
    assert report.needs_decision


def test_checker_detects_input_revisions_and_selected_only_scope(tmp_path):
    source = tmp_path / "acquisition.tif"
    pixels = np.zeros((8, 8), dtype=np.uint16)
    tifffile.imwrite(source, pixels, photometric="minisblack", metadata={"axes": "YX"})
    reader = FitsIO.from_path(source)
    state = ExperimentState.init(tmp_path, source)
    parent = None
    for step, role, name in [
        (cst.StepName.CONVERT, cst.ARTI_IMG_RAW, cst.FITS_ARRAY_RAW),
        (cst.StepName.REGISTER_CHANNEL, cst.ARTI_IMG_CHANNEL, cst.FITS_ARRAY_REG_CHANNEL),
        (cst.StepName.REGISTER_TIME, cst.ARTI_IMG_TIME, cst.FITS_ARRAY_REG_TIME),
        (cst.StepName.BG_SUB, cst.ARTI_IMG_BGSUB, cst.FITS_ARRAY_BGSUB),
    ]:
        refs = [] if parent is None else [{"artifact_path": parent.name, "created_at": reader.reader.metadata.fits_io.created_at}]
        if parent is None:
            refs = [{"artifact_path": source.name, "external": True, "created_at": None}]
        payload = reader.build_payload(export_channels="all", artifact_type=role,
                                       custom_metadata={"pipeline_meta": {"version": "4.0.0"}}).new_revision(refs)
        output = tmp_path / name
        reader.save_array(pixels, metadata=payload, output_path=output)
        state = state.with_complete_step(step_name=step, artifact_kind=role, artifact_path=output)
        parent = output
        reader = FitsIO.from_path(output)
    save_experiment_state(state)
    adapter = SettingsAdapter()
    for step in (cst.StepName.CONVERT, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME, cst.StepName.BG_SUB):
        adapter.set_step_enabled(step, True)
    config = adapter.as_mapping()
    assert not inspect_run(tmp_path, config).conflicts

    channel = tmp_path / cst.FITS_ARRAY_REG_CHANNEL
    old = FitsIO.from_path(channel)
    changed = old.reader.metadata.new_revision(old.reader.metadata.fits_io.derived_from)
    old.save_array(pixels + 1, metadata=changed, output_path=channel)
    report = inspect_run(tmp_path, config)
    assert {row.step for row in report.conflicts} == {cst.StepName.REGISTER_TIME, cst.StepName.BG_SUB}
    adapter.set_field_value(cst.StepName.REGISTER_CHANNEL, "overwrite", True)
    report = inspect_run(tmp_path, adapter.as_mapping())
    selected = apply_decision(adapter.as_mapping(), report, "selected")
    assert selected[cst.StepName.REGISTER_CHANNEL]["enabled"]
    assert not selected[cst.StepName.REGISTER_TIME]["enabled"]
    assert not selected[cst.StepName.BG_SUB]["enabled"]
    assert adapter.step_enabled(cst.StepName.REGISTER_TIME)
