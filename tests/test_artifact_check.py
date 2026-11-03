from dataclasses import replace

import numpy as np
from fits_io import FitsIO
import tifffile

from fits.environment import constant as cst
from fits.gui.settings import SettingsAdapter
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.decisions import apply_decision
from fits.workflows.experiments import ExperimentState, save_experiment_state


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
