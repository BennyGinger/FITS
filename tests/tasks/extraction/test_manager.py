from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from fits.environment.constant import ARTI_IMG, ARTI_TRACK
from fits.environment.state import ExperimentState
from fits.tasks.extraction.manager import ExtractionManager


class FakeFitsIO:
    readers: dict[str, FakeFitsIO] = {}

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
    def from_path(cls, path: Path) -> FakeFitsIO:
        return cls.readers[path.name]

    def get_array(self) -> SimpleNamespace:
        return self._array


def test_manager_automatically_loads_all_reference_artifacts(
        tmp_path: Path, monkeypatch,) -> None:
    image_path = tmp_path / "fits_array.tif"
    labels_path = tmp_path / "fits_track.tif"
    first_reference = tmp_path / "fits_ref_needle.tif"
    second_reference = tmp_path / "fits_ref_edge.tif"
    for path in (image_path, labels_path, first_reference, second_reference):
        path.touch()

    image = np.zeros((2, 2, 4, 4), dtype=np.uint16)
    labels = np.zeros((2, 4, 4), dtype=np.uint16)
    labels[:, 1:3, 1:3] = 1
    single_reference = np.zeros((2, 4, 4), dtype=np.uint8)
    multi_reference = np.zeros((2, 2, 4, 4), dtype=np.uint8)
    FakeFitsIO.readers = {
        image_path.name: FakeFitsIO(
            image, "TCYX", ("GFP", "RFP"), resolution=(0.5, 0.5)),
        labels_path.name: FakeFitsIO(labels, "TYX", ("GFP",)),
        first_reference.name: FakeFitsIO(single_reference, "TYX", ("GFP",)),
        second_reference.name: FakeFitsIO(multi_reference, "TCYX", ("GFP", "RFP")),}
    monkeypatch.setattr("fits.tasks.extraction.manager.FitsIO", FakeFitsIO)

    state = ExperimentState(
        workdir=tmp_path,
        artifacts={ARTI_IMG: image_path, ARTI_TRACK: labels_path},)
    manager = ExtractionManager(state)

    extractor = manager.prepare_quantification()

    assert set(extractor.array_data.references) == {"edge", "needle"}
    assert extractor.array_data.references["needle"].channel_labels == ("GFP",)
    assert extractor.array_data.references["edge"].channel_labels == ("GFP", "RFP")

    dataframe = manager.add_physical_distances(
        pd.DataFrame({"dist_pixel": [0.0, 4.0, np.nan]}))
    np.testing.assert_allclose(
        dataframe["dist_um"].to_numpy(dtype=float),
        [0.0, 2.0, np.nan],
        equal_nan=True,)
