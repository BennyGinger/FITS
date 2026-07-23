from __future__ import annotations

import numpy as np
import pytest

from fits.workflows.arrays.channel_merge import select_included_channels
from fits.workflows.arrays.merging import merge_channel


# ---- merge_channel ----

def test_merge_channel_no_existing_one_channel_preserves_squeezed_axes() -> None:
    new_array = np.ones((3, 4, 5), dtype=np.uint16)  # TYX

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=None,
        existing_axes=None,
        existing_channel_indices=None,
        new_array=new_array,
        new_axes="TYX",
        new_channel_indices=[1],
        reference_axes="TCYX",
    )

    assert merged_axes == "TYX"
    assert merged_array.shape == (3, 4, 5)
    assert merged_indices == [1]


def test_merge_channel_no_existing_multi_channel_preserves_axes() -> None:
    new_array = np.ones((3, 2, 4, 5), dtype=np.uint16)  # TCYX

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=None,
        existing_axes=None,
        existing_channel_indices=None,
        new_array=new_array,
        new_axes="TCYX",
        new_channel_indices=[1, 0],
        reference_axes="TCYX",
    )

    assert merged_axes == "TCYX"
    assert merged_array.shape == (3, 2, 4, 5)
    assert merged_indices == [1, 0]


def test_merge_channel_existing_tyx_plus_new_tyx_reference_tcyx_places_c_after_t() -> None:
    existing = np.full((3, 4, 5), 10, dtype=np.uint16)  # TYX, src=1
    new = np.full((3, 4, 5), 20, dtype=np.uint16)  # TYX, src=0

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=existing,
        existing_axes="TYX",
        existing_channel_indices=[1],
        new_array=new,
        new_axes="TYX",
        new_channel_indices=[0],
        reference_axes="TCYX",
    )

    assert merged_axes == "TCYX"
    assert merged_array.shape == (3, 2, 4, 5)
    assert merged_indices == [1, 0]


def test_merge_channel_existing_tyx_plus_new_tyx_reference_ctyx_places_c_front() -> None:
    existing = np.full((3, 4, 5), 10, dtype=np.uint16)  # TYX, src=1
    new = np.full((3, 4, 5), 20, dtype=np.uint16)  # TYX, src=0

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=existing,
        existing_axes="TYX",
        existing_channel_indices=[1],
        new_array=new,
        new_axes="TYX",
        new_channel_indices=[0],
        reference_axes="CTYX",
    )

    assert merged_axes == "CTYX"
    assert merged_array.shape == (2, 3, 4, 5)
    assert merged_indices == [1, 0]


def test_merge_channel_existing_tyx_plus_new_tyx_reference_tyx_uses_fallback_before_y() -> None:
    existing = np.full((3, 4, 5), 10, dtype=np.uint16)  # TYX, src=1
    new = np.full((3, 4, 5), 20, dtype=np.uint16)  # TYX, src=0

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=existing,
        existing_axes="TYX",
        existing_channel_indices=[1],
        new_array=new,
        new_axes="TYX",
        new_channel_indices=[0],
        reference_axes="TYX",
    )

    assert merged_axes == "TCYX"
    assert merged_array.shape == (3, 2, 4, 5)
    assert merged_indices == [1, 0]


def test_merge_channel_existing_tcyx_plus_new_tyx_preserves_tcyx() -> None:
    existing = np.full((3, 1, 4, 5), 10, dtype=np.uint16)  # TCYX, src=1
    new = np.full((3, 4, 5), 20, dtype=np.uint16)  # TYX, src=0

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=existing,
        existing_axes="TCYX",
        existing_channel_indices=[1],
        new_array=new,
        new_axes="TYX",
        new_channel_indices=[0],
        reference_axes="TCYX",
    )

    assert merged_axes == "TCYX"
    assert merged_array.shape == (3, 2, 4, 5)
    assert merged_indices == [1, 0]


def test_merge_channel_replaces_existing_identity_and_preserves_order() -> None:
    existing = np.stack(
        [
            np.full((4, 5), 10, dtype=np.uint16),  # src 1
            np.full((4, 5), 20, dtype=np.uint16),  # src 0
        ],
        axis=0,
    )  # CYX
    new = np.full((4, 5), 99, dtype=np.uint16)  # YX, src 1

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=existing,
        existing_axes="CYX",
        existing_channel_indices=[1, 0],
        new_array=new,
        new_axes="YX",
        new_channel_indices=[1],
        reference_axes="CYX",
    )

    assert merged_axes == "CYX"
    assert merged_indices == [1, 0]
    assert merged_array.shape == (2, 4, 5)
    assert np.all(merged_array[0] == 99)
    assert np.all(merged_array[1] == 20)


def test_merge_channel_appends_new_identity_in_new_order() -> None:
    existing = np.full((4, 5), 10, dtype=np.uint16)  # YX, src=1
    new = np.full((4, 5), 20, dtype=np.uint16)  # YX, src=0

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=existing,
        existing_axes="YX",
        existing_channel_indices=[1],
        new_array=new,
        new_axes="YX",
        new_channel_indices=[0],
        reference_axes="TCYX",
    )

    assert merged_axes == "CYX"
    assert merged_array.shape == (2, 4, 5)
    assert merged_indices == [1, 0]


def test_merge_channel_existing_one_channel_replaced_same_identity_stays_squeezed() -> None:
    existing = np.full((3, 4, 5), 10, dtype=np.uint16)  # TYX, src=1
    new = np.full((3, 4, 5), 20, dtype=np.uint16)  # TYX, src=1

    merged_array, merged_axes, merged_indices = merge_channel(
        existing_array=existing,
        existing_axes="TYX",
        existing_channel_indices=[1],
        new_array=new,
        new_axes="TYX",
        new_channel_indices=[1],
        reference_axes="TCYX",
    )

    assert merged_axes == "TYX"
    assert merged_array.shape == (3, 4, 5)
    assert merged_indices == [1]
    assert np.all(merged_array == 20)


# ---- apply_on_included_channels ----

def test_apply_on_included_channels_processes_full_array_without_exclusion() -> None:
    arr = np.stack([np.full((3, 3), 1, dtype=np.uint16), np.full((3, 3), 5, dtype=np.uint16)], axis=0)
    seen: dict[str, object] = {}

    def process_included(array_subset: np.ndarray, labels_subset: list[str] | None) -> np.ndarray:
        seen["shape"] = array_subset.shape
        seen["labels"] = labels_subset
        return array_subset + 2

    out = select_included_channels(arr, "CYX", ["GFP", "RFP"], None, process_included)
    assert seen["shape"] == (2, 3, 3)
    assert seen["labels"] == ["GFP", "RFP"]
    assert np.all(out[0] == 3)
    assert np.all(out[1] == 7)


def test_apply_on_included_channels_preserves_excluded_channel_values() -> None:
    arr = np.stack(
        [
            np.full((3, 3), 1, dtype=np.uint16),
            np.full((3, 3), 5, dtype=np.uint16),
            np.full((3, 3), 9, dtype=np.uint16),
        ],
        axis=0,
    )

    def process_included(array_subset: np.ndarray, labels_subset: list[str] | None) -> np.ndarray:
        assert labels_subset == ["GFP", "BF"]
        return array_subset + 10

    out = select_included_channels(arr, "CYX", ["GFP", "RFP", "BF"], ["RFP"], process_included)
    assert np.all(out[0] == 11)
    assert np.all(out[1] == 5)
    assert np.all(out[2] == 19)


def test_apply_on_included_channels_returns_copy_when_all_channels_excluded() -> None:
    arr = np.stack([np.full((3, 3), 1, dtype=np.uint16), np.full((3, 3), 5, dtype=np.uint16)], axis=0)
    called = {"process": False}

    def process_included(array_subset: np.ndarray, labels_subset: list[str] | None) -> np.ndarray:
        called["process"] = True
        return array_subset + 100

    out = select_included_channels(arr, "CYX", ["GFP", "RFP"], ["GFP", "RFP"], process_included)
    assert called["process"] is False
    assert np.array_equal(out, arr)
    assert out is not arr


def test_apply_on_included_channels_raises_for_unknown_excluded_label() -> None:
    arr = np.stack([np.full((3, 3), 1, dtype=np.uint16)], axis=0)

    def process_included(array_subset: np.ndarray, labels_subset: list[str] | None) -> np.ndarray:
        return array_subset

    with pytest.raises(ValueError, match="Unknown exclude_channel"):
        select_included_channels(arr, "CYX", ["GFP"], ["RFP"], process_included)
