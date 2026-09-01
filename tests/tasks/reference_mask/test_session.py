from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from fits.environment.constant import ARTI_REF, DIST_FITS
from fits.tasks.reference_mask import ReferenceMaskSession


class FakeFitsIO:
    def __init__(self, array: np.ndarray, axes: str, labels: list[str]) -> None:
        self._array = array
        self._axes = axes
        self.channel_labels = labels
        self.saved: dict[str, Any] | None = None

    def get_array(self) -> SimpleNamespace:
        return SimpleNamespace(array=self._array, axes=self._axes)

    def save_array(self, array: np.ndarray, **kwargs: Any) -> Path:
        self.saved = {"array": array.copy(), **kwargs}
        return kwargs["output_path"]


def create_session(tmp_path: Path,
                   monkeypatch: pytest.MonkeyPatch,
                   array: np.ndarray,
                   axes: str,
                   labels: list[str],
                   ) -> tuple[ReferenceMaskSession, FakeFitsIO]:
    source = tmp_path / "fits_array.tif"
    source.touch()
    reader = FakeFitsIO(array, axes, labels)
    monkeypatch.setattr(
        "fits.sessions.image.FitsIO.from_path", lambda _: reader)
    return ReferenceMaskSession(source), reader


def square(size: int, start: int, stop: int) -> np.ndarray:
    mask = np.zeros((size, size), dtype=np.uint8)
    mask[start:stop, start:stop] = 1
    return mask


def test_session_displays_image_and_stores_masks_by_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.arange(2 * 3 * 8 * 8).reshape(2, 3, 8, 8)
    session, _ = create_session(
        tmp_path, monkeypatch, image, "CTYX", ["GFP", "RFP"])
    gfp_mask = square(8, 1, 4)
    rfp_mask = square(8, 4, 7)

    session.set_mask_plane(gfp_mask, frame_index=1, channel="GFP")
    session.set_mask_plane(rfp_mask, frame_index=1, channel="RFP")

    np.testing.assert_array_equal(session.display_frame(1, "RFP"), image[1, 1])
    np.testing.assert_array_equal(session.mask_plane(1, "GFP"), gfp_mask)
    np.testing.assert_array_equal(session.mask_plane(1, "RFP"), rfp_mask)
    assert session.mask_array.shape == image.shape
    assert session.mask_array.dtype == np.uint8


def test_session_loads_a_channel_specific_reference_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "fits_array.tif"
    reference_path = tmp_path / "fits_ref_needle.tif"
    source.touch()
    reference_path.touch()
    source_reader = FakeFitsIO(
        np.zeros((3, 2, 8, 8)), "TCYX", ["RFP", "GFP"])
    reference_mask = np.zeros((3, 8, 8), dtype=np.uint8)
    reference_mask[1] = square(8, 2, 6)
    reference_reader = FakeFitsIO(reference_mask, "TYX", ["GFP"])
    monkeypatch.setattr(
        "fits.sessions.image.FitsIO.from_path",
        lambda path: (source_reader
                      if Path(path).name == "fits_array.tif"
                      else reference_reader),)

    session = ReferenceMaskSession(source, reference_path=reference_path)

    assert session.reference_label == "needle"
    assert session.loaded_channels == ("GFP",)
    assert not np.any(session.mask_array[:, 0])
    np.testing.assert_array_equal(session.mask_array[:, 1], reference_mask)


def test_completed_mask_fills_time_gaps_independently_by_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = create_session(
        tmp_path, monkeypatch, np.zeros((3, 2, 12, 12)),
        "TCYX", ["GFP", "RFP"])
    session.set_mask_plane(square(12, 1, 4), frame_index=0, channel="GFP")
    session.set_mask_plane(square(12, 5, 9), frame_index=2, channel="GFP")
    session.set_mask_plane(square(12, 2, 5), frame_index=0, channel="RFP")
    session.set_mask_plane(square(12, 6, 10), frame_index=2, channel="RFP")

    completed = session.completed_mask("T")

    assert np.all(np.any(completed != 0, axis=(2, 3)))
    assert not np.any(session.mask_array[1])


def test_set_mask_plane_rejects_nonbinary_or_wrong_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = create_session(
        tmp_path, monkeypatch, np.zeros((2, 8, 8)), "TYX", ["GFP"])

    with pytest.raises(ValueError, match="shape"):
        session.set_mask_plane(np.zeros((4, 4)), frame_index=0)
    with pytest.raises(ValueError, match="binary"):
        session.set_mask_plane(np.full((8, 8), 2), frame_index=0)


def test_save_uses_reference_name_and_completed_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, reader = create_session(
        tmp_path, monkeypatch, np.zeros((3, 8, 8)), "TYX", ["GFP"])
    session.set_mask_plane(square(8, 1, 4), frame_index=0)
    session.set_mask_plane(square(8, 4, 7), frame_index=2)

    output = session.save("nucleus", interpolation_axis="T")

    assert output == tmp_path / "fits_ref_nucleus.tif"
    assert reader.saved is not None
    assert reader.saved["artifact_kind"] == ARTI_REF
    assert reader.saved["created_by"] == DIST_FITS
    assert "custom_metadata" not in reader.saved
    assert reader.saved["array"].dtype == np.uint16
    assert set(np.unique(reader.saved["array"])) <= {0, 1}
    assert np.any(reader.saved["array"][1])
    assert not np.any(session.mask_array[1])


def test_save_exports_only_the_selected_source_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, reader = create_session(
        tmp_path, monkeypatch, np.zeros((3, 2, 8, 8)),
        "TCYX", ["RFP", "GFP"])
    session.set_mask_plane(square(8, 1, 4), frame_index=1, channel="GFP")

    session.save("needle", channel="GFP")

    assert reader.saved is not None
    assert reader.saved["array"].shape == (3, 8, 8)
    assert reader.saved["channel_labels"] == ("RFP", "GFP")
    assert reader.saved["export_channels"] == ["GFP"]
    np.testing.assert_array_equal(reader.saved["array"][1], square(8, 1, 4))


def test_save_appends_a_different_channel_to_an_existing_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, source_reader = create_session(
        tmp_path, monkeypatch, np.zeros((3, 2, 8, 8)),
        "TCYX", ["RFP", "GFP"])
    existing_mask = np.zeros((3, 8, 8), dtype=np.uint8)
    existing_mask[0] = square(8, 1, 4)
    existing_reader = FakeFitsIO(existing_mask, "TYX", ["GFP"])
    output = tmp_path / "fits_ref_needle.tif"
    output.touch()
    monkeypatch.setattr(
        "fits.tasks.reference_mask.artifact.FitsIO.from_path",
        lambda _: existing_reader,)
    session.set_mask_plane(square(8, 4, 7), frame_index=2, channel="RFP")

    session.save("needle", channel="RFP")

    assert source_reader.saved is not None
    assert source_reader.saved["array"].shape == (3, 2, 8, 8)
    assert source_reader.saved["export_channels"] == ["GFP", "RFP"]
    np.testing.assert_array_equal(source_reader.saved["array"][:, 0], existing_mask)
    np.testing.assert_array_equal(
        source_reader.saved["array"][2, 1], square(8, 4, 7))


def test_save_requires_overwrite_for_an_existing_channel_and_keeps_tyx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, source_reader = create_session(
        tmp_path, monkeypatch, np.zeros((3, 2, 8, 8)),
        "TCYX", ["RFP", "GFP"])
    existing_reader = FakeFitsIO(
        np.zeros((3, 8, 8), dtype=np.uint8), "TYX", ["GFP"])
    existing_reader._array[0] = square(8, 1, 4)
    output = tmp_path / "fits_ref_needle.tif"
    output.touch()
    monkeypatch.setattr(
        "fits.tasks.reference_mask.artifact.FitsIO.from_path",
        lambda _: existing_reader,)
    replacement = square(8, 4, 7)
    session.set_mask_plane(replacement, frame_index=2, channel="GFP")

    with pytest.raises(FileExistsError, match="GFP"):
        session.save("needle", channel="GFP")
    session.save("needle", channel="GFP", overwrite=True)

    assert source_reader.saved is not None
    assert source_reader.saved["array"].shape == (3, 8, 8)
    assert source_reader.saved["export_channels"] == ["GFP"]
    np.testing.assert_array_equal(source_reader.saved["array"][2], replacement)


def test_save_rejects_an_entirely_empty_reference_mask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = create_session(
        tmp_path, monkeypatch, np.zeros((3, 8, 8)), "TYX", ["GFP"])

    with pytest.raises(ValueError, match="without any drawn planes"):
        session.save("empty")


@pytest.mark.parametrize("label", ["", "../nucleus", "bad:name", "bad*"])
def test_save_rejects_unsafe_reference_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    session, _ = create_session(
        tmp_path, monkeypatch, np.zeros((2, 8, 8)), "TYX", ["GFP"])

    with pytest.raises(ValueError):
        session.save(label)
