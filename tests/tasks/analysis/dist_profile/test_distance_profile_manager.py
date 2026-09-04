from pathlib import Path
from types import SimpleNamespace

import numpy as np

from fits.environment.constant import ARTI_IMG
from fits.environment.state import ExperimentState
from fits.settings.models import DistanceProfileSettings
from fits.tasks.analysis.dist_profile.manager import DistanceProfileManager


class FakeFitsIO:
    def __init__(self, array: np.ndarray, axes: str) -> None:
        self._loaded = SimpleNamespace(array=array, axes=axes)
        self.channel_labels = ("GFP", "RFP")
        self.interval = 60.0
        self.resolution = (0.5, 0.5)

    @classmethod
    def from_path(cls, path: Path) -> "FakeFitsIO":
        return cls(IMAGE, "TZCYX")

    def get_array(self) -> SimpleNamespace:
        return self._loaded


IMAGE = np.zeros((2, 2, 2, 1, 5), dtype=np.uint16)
IMAGE[:, 0, 0, 0] = [10, 20, 30, 40, 50]
IMAGE[:, 1, 0, 0] = [15, 25, 35, 45, 55]
IMAGE[:, 0, 1, 0] = [100, 200, 300, 400, 500]
IMAGE[:, 1, 1, 0] = [150, 250, 350, 450, 550]


def test_manager_projects_z_and_builds_heatmap_ready_table(
        tmp_path: Path, monkeypatch,) -> None:
    image_path = tmp_path / "fits_array.tif"
    reference_path = tmp_path / "fits_ref_edge.tif"
    roi_path = tmp_path / "fits_roi_tailfin.tif"
    for path in (image_path, reference_path, roi_path):
        path.touch()
    reference = np.zeros_like(IMAGE, dtype=np.uint8)
    reference[0, 0, 1, 0, 0] = 1
    reference[1, 0, 1, 0, 2] = 1
    roi = np.zeros_like(IMAGE, dtype=np.uint8)
    roi[:, :, 1, 0, 1:4] = 4

    monkeypatch.setattr(
        "fits.tasks.analysis.manager.FitsIO", FakeFitsIO)
    monkeypatch.setattr(
        "fits.tasks.analysis.dist_profile.manager.load_reference_artifact",
        lambda *args, **kwargs: (reference, "edge", ("RFP",)))
    monkeypatch.setattr(
        "fits.tasks.analysis.dist_profile.manager.load_roi_artifact",
        lambda *args, **kwargs: (roi, "tailfin", ("RFP",)))

    state = ExperimentState(
        workdir=tmp_path,
        artifacts={ARTI_IMG: image_path},)
    settings = DistanceProfileSettings(bin_width=2)

    result = DistanceProfileManager(state, settings).calculate()

    assert len(result) == 24
    assert set(result["channel"]) == {"GFP", "RFP"}
    assert set(result["frame"]) == {1, 2}
    assert set(result["reference"]) == {"edge"}
    assert set(result["reference_channel"]) == {"RFP"}
    assert set(result["roi"].dropna()) == {"tailfin"}
    assert result["roi"].isna().any()
    assert set(result["roi_channel"].dropna()) == {"RFP"}
    assert set(result["z_projection"]) == {"max"}
    np.testing.assert_allclose(result["dist_um"].unique(), [0.5, 1.5, 2.5])

    first_gfp = result[(result["frame"] == 1)
                       & (result["channel"] == "GFP")
                       & (result["roi"] == "tailfin")]
    np.testing.assert_array_equal(first_gfp["pixel_count"], [1, 2, 0])
    np.testing.assert_allclose(first_gfp["mean_intensity"][:2], [25, 40])
    assert np.isnan(first_gfp.iloc[2]["mean_intensity"])

    second_gfp = result[(result["frame"] == 2)
                        & (result["channel"] == "GFP")
                        & (result["roi"] == "tailfin")]
    np.testing.assert_array_equal(second_gfp["pixel_count"], [3, 0, 0])
    assert np.isnan(second_gfp.iloc[1]["mean_intensity"])


def test_settings_parse_optional_values() -> None:
    settings = DistanceProfileSettings(maximum_bins="None")

    assert settings.maximum_bins is None
