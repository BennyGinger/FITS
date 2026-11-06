"""Quantification uses the mask source selected by included workflow steps."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import tifffile
from bioimagequant import CompartmentSettings

from fits.environment import constant as cst
from fits.tasks.analysis.extraction.manager import ExtractionManager, resolve_extraction_labels
from fits.tasks.analysis.extraction.compartment_export import export_compartments
from fits.workflows.definitions.inputs import configured_profile, resolve_inputs
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState
from fits.workflows.checks.artifacts import _configured_input_problem
from fits.workflows.checks.models import ArtifactRecord
from fits_io.metadata.models import FitsIOMeta


@pytest.fixture
def mask_state(tmp_path: Path) -> ExperimentState:
    """
    Keep distinct segmentation, tracking and edited labels alongside raw images.
    """
    for name, value in ((cst.FITS_ARRAY_RAW, 10), (cst.FITS_MASK_SEG, 1),
                        (cst.FITS_MASK_TRACK, 7), (cst.FITS_MASK_TRACK_EDITED, 9)):
        tifffile.imwrite(tmp_path / name, np.full((2, 8, 8), value, dtype=np.uint16),
                         imagej=True, metadata={"axes": "TYX"})
    return ExperimentState(workdir=tmp_path,
                           artifacts={cst.ARTI_IMG_RAW: Path(cst.FITS_ARRAY_RAW),
                                      cst.ARTI_SEG: Path(cst.FITS_MASK_SEG),
                                      cst.ARTI_TRACK: Path(cst.FITS_MASK_TRACK_EDITED)},
                           completed_steps=(cst.StepName.CONVERT, cst.StepName.SEGMENT,
                                            cst.StepName.TRACK, cst.StepName.EDIT_TRACK))


@pytest.mark.parametrize("tracking,editing,kind,name,value", [
    (False, False, cst.ARTI_SEG, cst.FITS_MASK_SEG, 1),
    (True, False, cst.ARTI_TRACK, cst.FITS_MASK_TRACK, 7),
    (True, True, cst.ARTI_TRACK, cst.FITS_MASK_TRACK_EDITED, 9),
])
def test_quantification_inputs_follow_inclusion(mask_state: ExperimentState,
                                               tracking: bool,
                                               editing: bool,
                                               kind: str,
                                               name: str,
                                               value: int,
                                               ) -> None:
    """
    Give bioimagequant exactly the chosen masks and record those same input paths.
    """
    config = {cst.StepName.SEGMENT: {"enabled": True}, cst.StepName.TRACK: {"enabled": tracking},
              cst.StepName.EDIT_TRACK: {"enabled": editing}}
    profile = configured_profile(REGISTRY[cst.StepName.EXTRACT].profile, config)
    selected_kind, path = resolve_extraction_labels(mask_state, profile)
    assert (selected_kind, path.name) == (kind, name)
    assert resolve_inputs(mask_state, profile)[kind] == path
    extractor = ExtractionManager(mask_state, profile=profile).prepare_quantification()
    assert set(extractor.array_data.object_labels) == {kind}
    assert np.all(extractor.array_data.object_labels[kind].array == value)


def test_missing_selected_mask_never_falls_back(mask_state: ExperimentState) -> None:
    """
    Reject missing tracking even when usable segmentation is still present.
    """
    profile = configured_profile(REGISTRY[cst.StepName.EXTRACT].profile,
                                 {cst.StepName.TRACK: {"enabled": True}})
    (mask_state.workdir / cst.FITS_MASK_TRACK).unlink()
    with pytest.raises(ValueError, match="selected tracking mask"):
        resolve_extraction_labels(mask_state, profile)


def test_editing_requires_an_accepted_result(mask_state: ExperimentState) -> None:
    """
    Do not silently accept unreviewed tracking when editing is included.
    """
    state = replace(mask_state, completed_steps=(cst.StepName.CONVERT, cst.StepName.SEGMENT, cst.StepName.TRACK))
    profile = configured_profile(REGISTRY[cst.StepName.EXTRACT].profile,
                                 {cst.StepName.TRACK: {"enabled": True}, cst.StepName.EDIT_TRACK: {"enabled": True}})
    with pytest.raises(ValueError, match="accepted Edit tracking"):
        resolve_extraction_labels(state, profile)


def test_compartment_exports_use_the_selected_segmentation(mask_state: ExperimentState) -> None:
    """
    Export compartments beside selected segmentation while retaining bypassed tracking files.
    """
    profile = configured_profile(REGISTRY[cst.StepName.EXTRACT].profile,
                                 {cst.StepName.SEGMENT: {"enabled": True}})
    paths = export_compartments(mask_state, CompartmentSettings(membrane_thickness=1), profile=profile)
    assert {path.name for path in paths} == {"fits_masks_seg_mb.tif", "fits_masks_seg_cyto.tif"}
    assert all(path.is_file() for path in paths)
    assert not (mask_state.workdir / "fits_masks_track_mb.tif").exists()


def test_accepted_edits_do_not_treat_themselves_as_new_inputs(mask_state: ExperimentState) -> None:
    """
    Check saved edit provenance without comparing the accepted output against itself.
    """
    metadata = FitsIOMeta().new_revision([{"artifact_path": cst.FITS_MASK_TRACK},
                                         {"artifact_path": cst.FITS_ARRAY_RAW}])
    record = ArtifactRecord(mask_state.workdir / cst.FITS_MASK_TRACK_EDITED, cst.StepName.EDIT_TRACK, metadata)
    config = {cst.StepName.TRACK: {"enabled": True}, cst.StepName.EDIT_TRACK: {"enabled": True}}
    assert not _configured_input_problem(record, mask_state, config)
