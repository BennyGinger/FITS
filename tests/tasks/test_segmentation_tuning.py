from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from fits.settings.models import SegmentSettings
from fits.tasks.segmentation.tuning import SegmentationTuningSession


class FakeFitsIO:
    def __init__(self, array: np.ndarray, axes: str, labels: list[str]) -> None:
        self._array = array
        self._axes = axes
        self.channel_labels = labels
        self.label_resolution_calls: list[list[str]] = []

    def get_array(self) -> SimpleNamespace:
        return SimpleNamespace(array=self._array, axes=self._axes)

    def labels_to_indices(self, labels: list[str]) -> list[int]:
        self.label_resolution_calls.append(labels)
        return [self.channel_labels.index(label) for label in labels]


class FakeWrapper:
    def __init__(self) -> None:
        self.calls: list[tuple[np.ndarray, str]] = []
        self.setup_calls = 0
        self.output_axis_order = "YX"

    def setup(self) -> None:
        self.setup_calls += 1

    def run(self, array: np.ndarray, axes: str) -> np.ndarray:
        self.calls.append((array.copy(), axes))
        self.output_axis_order = axes
        return np.full(array.shape, 7, dtype=np.uint16)


def _settings(**user_settings: object) -> SegmentSettings:
    return SegmentSettings(
        channel_to_segment=["RFP"],
        do_denoise=False,
        user_settings={"model_type": "test", **user_settings},
    )


def test_session_navigates_noncanonical_time_and_channel_axes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "fits_array.tif"
    source.touch()
    array = np.arange(2 * 3 * 4 * 5).reshape(2, 3, 4, 5)
    reader = FakeFitsIO(array, "CTYX", ["GFP", "RFP"])
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.FitsIO.from_path",
        lambda _: reader,
    )

    with SegmentationTuningSession(source, cache_parent=tmp_path) as session:
        assert session.axes == "CTYX"
        assert session.frame_count == 3
        assert session.channel_labels == ("GFP", "RFP")
        display = session.display_frame(2, "RFP")
        np.testing.assert_array_equal(display, array[1, 2])
        assert np.shares_memory(display, array)


def test_preview_is_cached_by_frame_channels_and_settings_and_cleaned_on_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "fits_array.tif"
    source.touch()
    array = np.arange(3 * 2 * 4 * 5).reshape(3, 2, 4, 5)
    reader = FakeFitsIO(array, "TCYX", ["GFP", "RFP"])
    wrapper = FakeWrapper()
    wrapper_settings: list[dict] = []
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.FitsIO.from_path",
        lambda _: reader,
    )
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.CellposeWrapper.from_dict",
        lambda settings: wrapper_settings.append(settings) or wrapper,
    )

    session = SegmentationTuningSession(source,
                                        segment_settings=_settings(),
                                        cache_parent=tmp_path,)
    cache_dir = session.cache_dir
    first = session.run_preview(1, "RFP", user_settings={"cellprob_threshold": 0.0})
    second = session.run_preview(1, "RFP", user_settings={"cellprob_threshold": 0.0})
    changed = session.run_preview(1, "RFP", user_settings={"cellprob_threshold": 1.0})
    cached = session.load_cached_preview(
        1,
        "RFP",
        user_settings={"cellprob_threshold": 0.0},)

    assert first.from_cache is False
    assert second.from_cache is True
    assert changed.from_cache is False
    assert cached is not None
    assert cached.from_cache is True
    assert first.cache_path == second.cache_path
    assert changed.cache_path != first.cache_path
    assert first.cache_path.name.startswith("frame_000001__RFP__")
    assert first.cache_path.is_file()
    assert len(wrapper.calls) == 2
    np.testing.assert_array_equal(wrapper.calls[0][0], array[1, 1])
    assert wrapper.calls[0][1] == "YX"
    assert wrapper_settings[0]["user_settings"] == {
        "model_type": "test",
        "cellprob_threshold": 0.0,}
    assert reader.label_resolution_calls == [["RFP"], ["RFP"], ["RFP"], ["RFP"]]

    session.close()

    assert session.closed is True
    assert cache_dir.exists() is False
    with pytest.raises(RuntimeError, match="closed"):
        session.display_frame(0)


def test_session_preserves_z_and_selects_planes_only_for_display(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "fits_array.tif"
    source.touch()
    array = np.arange(2 * 1 * 3 * 4 * 5).reshape(2, 1, 3, 4, 5)
    reader = FakeFitsIO(array, "TCZYX", ["GFP"])
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.FitsIO.from_path",
        lambda _: reader,
    )

    with SegmentationTuningSession(source, cache_parent=tmp_path) as session:
        assert session.axes == "TCZYX"
        assert session.shape == array.shape
        assert session.plane_count == 3
        np.testing.assert_array_equal(
            session.display_frame(1, "GFP", z_index=2),
            array[1, 0, 2],
        )


def test_preview_passes_z_axis_unchanged_to_cellpose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "fits_array.tif"
    source.touch()
    array = np.arange(2 * 1 * 3 * 4 * 5).reshape(2, 1, 3, 4, 5)
    reader = FakeFitsIO(array, "TCZYX", ["RFP"])
    wrapper = FakeWrapper()
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.FitsIO.from_path",
        lambda _: reader,
    )
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.CellposeWrapper.from_dict",
        lambda _: wrapper,
    )

    with SegmentationTuningSession(source,
                                   segment_settings=_settings(),
                                   cache_parent=tmp_path,) as session:
        preview = session.run_preview(
            1,
            "RFP",
            user_settings={"do_3D": True},)

        np.testing.assert_array_equal(wrapper.calls[0][0], array[1, 0])
        assert wrapper.calls[0][1] == "ZYX"
        assert preview.mask_axes == "ZYX"
        assert preview.mask.shape == (3, 4, 5)


def test_2d_preview_uses_the_displayed_z_plane(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch,
                                              ) -> None:
    source = tmp_path / "fits_array.tif"
    source.touch()
    array = np.arange(1 * 3 * 4 * 5).reshape(1, 3, 4, 5)
    reader = FakeFitsIO(array, "CZYX", ["GFP"])
    wrapper = FakeWrapper()
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.FitsIO.from_path",
        lambda _: reader,)
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.CellposeWrapper.from_dict",
        lambda _: wrapper,)

    with SegmentationTuningSession(source, cache_parent=tmp_path) as session:
        session.run_preview(0, "GFP", z_index=2)

    np.testing.assert_array_equal(wrapper.calls[0][0], array[0, 2])
    assert wrapper.calls[0][1] == "YX"


def test_preview_resolves_display_and_nuclear_channels_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "fits_array.tif"
    source.touch()
    array = np.arange(1 * 2 * 4 * 5).reshape(1, 2, 4, 5)
    reader = FakeFitsIO(array, "TCYX", ["GFP", "RFP"])
    wrapper = FakeWrapper()
    settings = SegmentSettings(channel_to_segment=["RFP"],
                               nuclear_channel="GFP",
                               do_denoise=False,)
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.FitsIO.from_path",
        lambda _: reader,)
    monkeypatch.setattr(
        "fits.tasks.segmentation.tuning.CellposeWrapper.from_dict",
        lambda _: wrapper,)

    with SegmentationTuningSession(source,
                                   segment_settings=settings,
                                   cache_parent=tmp_path,) as session:
        session.run_preview(0, "RFP")

    assert reader.label_resolution_calls == [["RFP"], ["GFP"]]
    np.testing.assert_array_equal(wrapper.calls[0][0], array[0, [1, 0]])
    assert wrapper.calls[0][1] == "CYX"


def test_session_rejects_non_fits_image_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "input.tif"
    source.touch()

    with pytest.raises(ValueError, match="fits_array.tif"):
        SegmentationTuningSession(source, cache_parent=tmp_path)


def test_session_reports_missing_source_before_filename_validation(tmp_path: Path) -> None:
    source = tmp_path / "fits_array.tif"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        SegmentationTuningSession(source, cache_parent=tmp_path)
