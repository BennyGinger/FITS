from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from fits.environment.constant import ARTI_ROI, DIST_FITS
from fits.tasks.roi_mask import RoiSession
from fits.tasks.roi_mask.artifact import (
    ROI_MASK_ENCODING, ROI_MASK_VALUE_TABLE, _normalize_roi_encoding,
    merge_roi_channels,
)


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


def create_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                   image: np.ndarray, axes: str = "TYX",
                   labels: list[str] | None = None) -> tuple[RoiSession, FakeFitsIO]:
    source = tmp_path / "fits_array.tif"
    source.touch()
    reader = FakeFitsIO(image, axes, labels or ["GFP"])
    monkeypatch.setattr("fits.sessions.image.FitsIO.from_path", lambda _: reader)
    return RoiSession(source), reader


def test_threshold_plane_uses_editable_lower_and_upper_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.arange(16).reshape(1, 4, 4)
    session, _ = create_session(tmp_path, monkeypatch, image)

    mask = session.threshold_plane(4, 10)

    expected = np.where(
        (image[0] > 4) & (image[0] <= 10),
        session.THRESHOLD_INCLUDED, session.THRESHOLD_EXCLUDED)
    np.testing.assert_array_equal(mask, expected)
    np.testing.assert_array_equal(session.mask_plane(), mask)
    np.testing.assert_array_equal(session.display_mask_plane(), expected >= 3)


def test_threshold_preserves_manual_additions_and_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.arange(16).reshape(1, 4, 4)
    session, _ = create_session(tmp_path, monkeypatch, image)
    session.threshold_plane(4, 10)
    edited = session.display_mask_plane()
    edited[0, 0] = 1
    edited[2, 0] = 0
    session.apply_display_edit(edited)

    session.threshold_plane(12, 15)

    states = session.mask_plane()
    assert session._manually_added(states)[0, 0]
    assert session._manually_excluded(states)[2, 0]
    assert session._threshold_included(states)[3, 3]
    assert states[1, 1] == 0


def test_add_gesture_marks_the_complete_shape_as_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.arange(36).reshape(1, 6, 6)
    session, _ = create_session(tmp_path, monkeypatch, image)
    session.threshold_plane(10, 30)
    shape = np.zeros((6, 6), dtype=bool)
    shape[1:5, 1:5] = True
    visible = session.display_mask_plane()
    visible[shape] = 1

    session.apply_display_edit(
        visible, edited_pixels=shape, operation="add")

    assert np.all(session._manually_added(session.mask_plane())[shape])


def test_fill_holes_records_manual_inclusions_and_is_undoable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = create_session(tmp_path, monkeypatch, np.zeros((1, 7, 7)))
    states = np.zeros((7, 7), dtype=np.uint8)
    states[1:6, 1:6] = session.THRESHOLD_INCLUDED
    states[3, 3] = session.THRESHOLD_EXCLUDED
    session.set_mask_plane(states)

    assert session.fill_holes() is True
    assert session.mask_plane()[3, 3] == session.MANUALLY_INCLUDED
    assert session.display_mask_plane()[3, 3] == 1

    session.undo_display_edit()
    assert session.mask_plane()[3, 3] == session.THRESHOLD_EXCLUDED


def test_remove_small_objects_records_manual_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = create_session(tmp_path, monkeypatch, np.zeros((1, 8, 8)))
    states = np.zeros((8, 8), dtype=np.uint8)
    states[1:3, 1:3] = session.THRESHOLD_INCLUDED
    states[4:8, 4:8] = session.THRESHOLD_INCLUDED
    session.set_mask_plane(states)

    assert session.remove_small_objects(5) is True

    result = session.mask_plane()
    assert np.all(
        result[1:3, 1:3] == session.THRESHOLD_INCLUDED_MANUALLY_EXCLUDED)
    assert np.all(result[4:8, 4:8] == session.THRESHOLD_INCLUDED)
    assert not np.any(session.display_mask_plane()[1:3, 1:3])


def test_undo_restores_ordered_state_plane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = create_session(tmp_path, monkeypatch, np.arange(16).reshape(1, 4, 4))
    original = session.threshold_plane(4, 10)
    edited = session.display_mask_plane()
    edited[0, 0] = 1
    session.apply_display_edit(edited)

    restored = session.undo_display_edit()

    np.testing.assert_array_equal(session.mask_plane(), original)
    np.testing.assert_array_equal(restored, original >= 3)


def test_interpolation_completes_only_manual_roi_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((3, 6, 6), dtype=np.uint16)
    session, _ = create_session(tmp_path, monkeypatch, image)
    states = np.zeros((6, 6), dtype=np.uint8)
    states[1:4, 1:4] = session.MANUALLY_INCLUDED

    session.set_mask_plane(states, frame_index=0)
    session.set_mask_plane(states, frame_index=2)
    preview = session.interpolated_display_mask_plane(
        "T", frame_index=1)

    assert np.all(preview[1:4, 1:4])
    assert not np.any(preview[0])
    session.set_mask_plane(states, frame_index=0)
    session.set_mask_plane(states, frame_index=2)

    completed = session._complete_manual_corrections(
        session.mask_array, "TYX", "T", True, True)

    assert np.all(completed[1, 1:4, 1:4] == session.MANUALLY_INCLUDED)
    assert np.all(completed[1, :1] == 0)


def test_otsu_separates_a_two_level_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((1, 20, 20), dtype=np.uint16)
    image[:, :, 10:] = 1000
    session, _ = create_session(tmp_path, monkeypatch, image)

    threshold = session.otsu_threshold()

    assert 0 <= threshold < 1000


def test_threshold_and_clear_whole_stack_for_one_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((2, 2, 2, 6, 6), dtype=np.uint16)
    image[:, 1, :, :, 3:] = 1000
    session, _ = create_session(
        tmp_path, monkeypatch, image, "TCZYX", ["GFP", "RFP"])

    session.threshold_stack(channel="RFP")

    assert np.all(np.any(session._included(session.mask_array[:, 1]), axis=(2, 3)))
    assert not np.any(session._included(session.mask_array[:, 0]))

    session.clear_stack(channel="RFP")

    assert not np.any(session.mask_array)


def test_manual_range_is_applied_to_each_stack_plane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.arange(2 * 4 * 4).reshape(2, 4, 4)
    session, _ = create_session(tmp_path, monkeypatch, image)

    session.threshold_stack_range(5, 20)

    np.testing.assert_array_equal(
        session.mask_array, np.where(
            (image > 5) & (image <= 20), session.THRESHOLD_INCLUDED,
            session.THRESHOLD_EXCLUDED))
    assert session.threshold_range(frame_index=0) == (5.0, 20.0)
    assert session.threshold_range(frame_index=1) == (5.0, 20.0)

    session.clear_mask_plane(frame_index=1)

    assert session.threshold_range(frame_index=1) is None


def test_automatic_threshold_clears_a_constant_plane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((1, 6, 6), 42, dtype=np.uint16)
    session, _ = create_session(tmp_path, monkeypatch, image)
    session.set_mask_plane(np.full(
        (6, 6), session.THRESHOLD_INCLUDED, dtype=np.uint8))

    threshold = session.apply_otsu()

    assert threshold is None
    assert not np.any(session.mask_plane())
    assert not np.any(session.display_mask_plane())


def test_save_uses_roi_name_artifact_and_selected_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((2, 2, 6, 6), dtype=np.uint16)
    session, reader = create_session(
        tmp_path, monkeypatch, image, "TCYX", ["GFP", "RFP"])
    mask = np.zeros((6, 6), dtype=np.uint8)
    mask[1:4, 2:5] = session.MANUALLY_INCLUDED
    session.set_mask_plane(mask, frame_index=1, channel="RFP")

    output = session.save("tail", channel="RFP")

    assert output == tmp_path / "fits_roi_tail.tif"
    assert reader.saved is not None
    assert reader.saved["artifact_kind"] == ARTI_ROI
    assert reader.saved["created_by"] == DIST_FITS
    assert reader.saved["export_channels"] == ["RFP"]
    assert reader.saved["array"].dtype == np.uint16
    assert reader.saved["custom_metadata"] == {
        "roi_mask_encoding": ROI_MASK_ENCODING,
        "roi_mask_value_table": ROI_MASK_VALUE_TABLE,
    }
    np.testing.assert_array_equal(reader.saved["array"][1], mask)


def test_current_ordered_roi_states_are_not_reinterpreted() -> None:
    states = np.asarray([0, 1, 2, 3, 4, 5], dtype=np.uint8)

    loaded = _normalize_roi_encoding(
        states, encoding=ROI_MASK_ENCODING)

    np.testing.assert_array_equal(loaded, states)


def test_roi_without_current_encoding_is_rejected() -> None:
    with pytest.raises(ValueError, match="ordered-threshold-manual-v2"):
        _normalize_roi_encoding(np.asarray([0, 1]), encoding=None)


def test_saving_replaces_an_artifact_without_current_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "fits_roi_tail.tif"
    output.touch()
    old_reader = SimpleNamespace(fits_metadata={})
    monkeypatch.setattr(
        "fits.tasks.roi_mask.artifact.FitsIO.from_path", lambda _: old_reader)
    current = np.full((2, 3, 3), 4, dtype=np.uint8)

    merged, labels = merge_roi_channels(
        output, current, channel_axes="TYX", source_axes="TCYX",
        channel_label="GFP", overwrite=False)

    np.testing.assert_array_equal(merged, current)
    assert labels == ["GFP"]
