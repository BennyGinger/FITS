from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from fisch.environment.constant import ARTI_IMG, ARTI_TRACK
from fisch.workflows.experiments import ExperimentState
from fisch.tasks.analysis.extraction.manager import ExtractionManager


class FakeScopeIO:
    readers: dict[str, FakeScopeIO] = {}

    def __init__(self,
                 array: np.ndarray,
                 axes: str,
                 channel_labels: tuple[str, ...],
                 *,
                 resolution: tuple[float, float] | None = None,
                 ) -> None:
        self._array = SimpleNamespace(array=array, axes=axes)
        self.channel_labels = channel_labels
        self.interval = None
        self.resolution = resolution

    @classmethod
    def from_path(cls, path: Path) -> FakeScopeIO:
        return cls.readers[path.name]

    def get_array(self) -> SimpleNamespace:
        return self._array


def test_manager_automatically_loads_all_reference_artifacts(
        tmp_path: Path, monkeypatch,) -> None:
    image_path = tmp_path / "proc_array.tif"
    labels_path = tmp_path / "proc_masks_track.tif"
    first_reference = tmp_path / "proc_ref_needle.tif"
    second_reference = tmp_path / "proc_ref_edge.tif"
    for path in (image_path, labels_path, first_reference, second_reference):
        path.touch()

    image = np.zeros((2, 2, 2, 4, 4), dtype=np.uint16)
    image[:, 1] = 10
    labels = np.zeros((2, 2, 4, 4), dtype=np.uint16)
    labels[:, 1, 1:3, 1:3] = 1
    single_reference = np.zeros((2, 2, 4, 4), dtype=np.uint8)
    single_reference[:, 1, 1, 1] = 1
    multi_reference = np.zeros((2, 2, 2, 4, 4), dtype=np.uint8)
    multi_reference[:, 1, :, 2, 2] = 1
    FakeScopeIO.readers = {
        image_path.name: FakeScopeIO(
            image, "TZCYX", ("GFP", "RFP"), resolution=(0.5, 0.5)),
        labels_path.name: FakeScopeIO(labels, "TZYX", ("GFP",)),
        first_reference.name: FakeScopeIO(
            single_reference, "TZYX", ("GFP",)),
        second_reference.name: FakeScopeIO(
            multi_reference, "TZCYX", ("GFP", "RFP")),}
    monkeypatch.setattr("fisch.tasks.analysis.extraction.manager.ScopeIO", FakeScopeIO)
    monkeypatch.setattr("fisch.tasks.analysis.manager.ScopeIO", FakeScopeIO)

    state = ExperimentState(
        workdir=tmp_path,
        artifacts={ARTI_IMG: image_path, ARTI_TRACK: labels_path},)
    manager = ExtractionManager(state)

    extractor = manager.prepare_quantification()

    assert set(extractor.array_data.references) == {"edge", "needle"}
    assert extractor.array_data.references["needle"].channel_labels == ("GFP",)
    assert extractor.array_data.references["edge"].channel_labels == ("GFP", "RFP")
    assert extractor.array_data.intensity is not None
    assert extractor.array_data.intensity.axes == "TYXC"
    assert extractor.array_data.intensity.array.shape == (2, 4, 4, 2)
    assert extractor.array_data.object_labels[ARTI_TRACK].axes == "TYX"
    assert extractor.array_data.object_labels[ARTI_TRACK].array.shape == (2, 4, 4)
    assert extractor.array_data.references["needle"].axes == "TYX"

    assert extractor.pixel_size == 0.5


import pytest
@pytest.fixture(autouse=True)
def isolate_geometry_metadata(monkeypatch):
    # Readers in this numerical test are in-memory arrays, not TIFF files.
    monkeypatch.setattr('fisch.tasks.analysis.manager.refresh_branch', lambda *args: None)
