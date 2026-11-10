"""Real FITS exports and compaction of optional derived cell masks."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import tifffile
from bioimagequant import CompartmentSettings, compartment_masks
from scope_io import ScopeIO

from fits.environment import constant as cst
from fits.gui.settings import SettingsAdapter
from fits.pipeline import start_pipeline
from fits.settings.models import ExtractSettings
from fits.tasks.analysis.extraction.compartment_export import compartment_export_paths
from fits.tasks.analysis.extraction.extract import extract
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState, discover_saved_states, save_experiment_state
from fits.workflows.file_management.compaction import apply_compaction, plan_compaction


@pytest.fixture
def tracked_experiment(tmp_path: Path) -> ExperimentState:
    """
    Create a genuine two-frame/channel FITS experiment without segmentation hardware.
    """
    source = tmp_path / "source.tif"
    image = np.arange(2 * 2 * 8 * 8, dtype=np.uint16).reshape(2, 2, 8, 8)
    tifffile.imwrite(source, image, photometric="minisblack", metadata={"axes": "TCYX"})
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "Test"
    adapter.set_runtime_value("execution", "batch")
    adapter.set_field_value(cst.StepName.CONVERT, "channel_labels", ["Red", "Green"])
    start_pipeline(adapter.save_to_run_dir(), terminal_progress=False)
    state = discover_saved_states(tmp_path)[0]
    image_path = state.artifact(cst.ARTI_IMG)
    assert image_path is not None
    reader = ScopeIO.from_path(image_path)
    labels = np.zeros_like(image)
    labels[:, 0, :4, :4] = 24
    labels[:, 1, 3:7, 3:7] = 91
    path = reader.save_array(labels, output_path=state.workdir / cst.FITS_MASK_TRACK,
                             artifact_kind=cst.ARTI_TRACK)
    state = state.with_complete_step(step_name=cst.StepName.TRACK,
                                     artifact_kind=cst.ARTI_TRACK, artifact_path=path)
    return save_experiment_state(state)


def test_exports_preserve_source_channels_labels_and_provenance_then_compact(
        tracked_experiment: ExperimentState,
        ) -> None:
    """
    Export actual TIFFs, verify their pixels/metadata, and remove only derivatives.
    """
    state = tracked_experiment
    source = state.artifact(cst.ARTI_TRACK)
    assert source is not None
    original = source.read_bytes()
    settings = ExtractSettings(compartments=True, save_compartment_masks=True,
                               membrane_thickness=1, dilation_radius=1, frame_workers=1)
    updated = extract(settings, state, REGISTRY[cst.StepName.EXTRACT].profile)[0]
    mb_path, cyto_path = compartment_export_paths(source)
    raw = ScopeIO.from_path(source).get_array()
    assert raw.axes == "TCYX"
    for path, name in [(mb_path, "mb"), (cyto_path, "cyto")]:
        reader = ScopeIO.from_path(path)
        actual = reader.get_array()
        assert actual.axes == raw.axes
        assert reader.channel_labels == ["Red", "Green"]
        metadata = reader.reader.metadata
        assert metadata.artifact.artifact_type == f"compartment_{name}"
        references = metadata.artifact.derived_from
        assert isinstance(references, list)
        assert references[0]["created_at"] == ScopeIO.from_path(source).reader.metadata.artifact.created_at
        assert metadata.custom_metadata["compartments"]["dilation_radius"] == 1
        for frame in range(2):
            for channel in range(2):
                expected = compartment_masks(raw.array[frame, channel], CompartmentSettings(1, 1))[name]
                np.testing.assert_array_equal(actual.array[frame, channel], expected)
    assert source.read_bytes() == original
    table_path = updated.artifact(cst.ARTI_QUANTI)
    assert table_path is not None
    table_bytes = table_path.read_bytes()
    table = pd.read_parquet(table_path)
    assert set(table["compartment"]) == {"full", "mb", "cyto"}
    assert state.run_dir is not None
    plan = plan_compaction(state.run_dir)
    assert mb_path in plan.remove and cyto_path in plan.remove
    apply_compaction(plan)
    assert not mb_path.exists() and not cyto_path.exists()
    assert table_path.read_bytes() == table_bytes
    assert (state.workdir / cst.FITS_MASKS_COMPACTED).is_file()


def test_disabled_export_creates_no_tiffs(tracked_experiment: ExperimentState) -> None:
    """
    Keep optional file generation off while still measuring compartments.
    """
    state = tracked_experiment
    source = state.artifact(cst.ARTI_TRACK)
    assert source is not None
    extract(ExtractSettings(compartments=True, frame_workers=1), state, REGISTRY[cst.StepName.EXTRACT].profile)
    assert all(not path.exists() for path in compartment_export_paths(source))


@pytest.mark.parametrize("save_masks", [False, True])
def test_full_rebuild_after_compaction_obeys_saved_export_setting(
        tracked_experiment: ExperimentState, monkeypatch: pytest.MonkeyPatch, save_masks: bool,
        ) -> None:
    """
    Exercise the real rebuild chain, substituting only GPU segmentation/tracking.
    """
    from dataclasses import replace
    from typing import Any
    from fits.settings.loader import run_settings_path
    from fits.tasks.common.artifact_results import save_step_result
    from fits.tasks.common.preparation import load_input_reader
    from fits.workflows.definitions.models import StepProfile
    from fits.workflows.file_management.rebuild import execute_plan, plan_full_rebuild

    state = tracked_experiment
    assert state.run_dir is not None
    root = state.run_dir
    extract(ExtractSettings(compartments=True, save_compartment_masks=True, frame_workers=1),
            state, REGISTRY[cst.StepName.EXTRACT].profile)
    apply_compaction(plan_compaction(root))
    adapter = SettingsAdapter()
    adapter.load(run_settings_path(root))
    adapter.set_segment_channels([{"channel": "Red"}, {"channel": "Green"}])
    adapter.set_field_value(cst.StepName.TRACK, "channel_to_track", ["Red", "Green"])
    adapter.set_field_value(cst.StepName.EXTRACT, "compartments", True)
    adapter.set_field_value(cst.StepName.EXTRACT, "save_compartment_masks", save_masks)
    adapter.set_field_value(cst.StepName.EXTRACT, "frame_workers", 1)
    adapter.save_to_run_dir()

    def mask_step(settings: Any, state: ExperimentState, profile: StepProfile) -> list[ExperimentState]:
        """
        Publish deterministic masks with ordinary workflow revision provenance.
        """
        reader = load_input_reader(state, profile)
        labels = np.zeros_like(reader.get_array().array, dtype=np.uint16)
        labels[:, :, 1:7, 1:7] = 24
        updated = state.with_metadata(step_name=profile.step_name, created_by=profile.distribution)
        return [save_step_result(reader, labels, list(reader.channel_labels), updated, profile)]

    for step in (cst.StepName.SEGMENT, cst.StepName.TRACK):
        monkeypatch.setitem(REGISTRY, step, replace(REGISTRY[step], item_runner=mask_step))
    plan = plan_full_rebuild(root)
    assert plan is not None
    execute_plan(plan, lambda reviewed: start_pipeline(adapter.save_to_run_dir(),
                                                       maintenance=reviewed, terminal_progress=False))
    restored = discover_saved_states(root)[0]
    source = restored.artifact(cst.ARTI_TRACK)
    assert source is not None and source.is_file()
    assert all(path.is_file() == save_masks for path in compartment_export_paths(source))
    table_path = restored.artifact(cst.ARTI_QUANTI)
    assert table_path is not None
    assert set(pd.read_parquet(table_path)["compartment"]) == {"full", "mb", "cyto"}


def test_exporting_completed_quantification_keeps_measurement_bytes(tracked_experiment: ExperimentState) -> None:
    """
    Produce requested masks without rewriting an already completed measurement table.
    """
    state = extract(ExtractSettings(compartments=True, frame_workers=1), tracked_experiment,
                    REGISTRY[cst.StepName.EXTRACT].profile)[0]
    path = state.artifact(cst.ARTI_QUANTI)
    assert path is not None
    original = path.read_bytes()
    extract(ExtractSettings(compartments=True, save_compartment_masks=True, frame_workers=1),
            state, REGISTRY[cst.StepName.EXTRACT].profile)
    assert path.read_bytes() == original
    source = state.artifact(cst.ARTI_TRACK)
    assert source is not None
    assert all(path.is_file() for path in compartment_export_paths(source))
