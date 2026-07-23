from __future__ import annotations

import numpy as np
import pytest

from fits.workflows.arrays.validations import validate_axes_rank, validate_axis_order, validate_channel_count, validate_channel_labels_exist, validate_no_duplicate_axes


# ---- validate_no_duplicate_axes ----

def test_validate_no_duplicate_axes_accepts_unique_axes() -> None:
    validate_no_duplicate_axes("TCZYX")  # should not raise


def test_validate_no_duplicate_axes_raises_on_duplicate() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_no_duplicate_axes("CCY")


# ---- validate_axes_rank ----

def test_validate_axes_rank_accepts_matching_rank() -> None:
    validate_axes_rank(np.zeros((3, 4)), "YX")  # should not raise


def test_validate_axes_rank_raises_on_mismatch() -> None:
    with pytest.raises(ValueError, match="do not match array shape"):
        validate_axes_rank(np.zeros((3, 4, 5)), "YX")


def test_validate_axes_rank_includes_label_in_message() -> None:
    with pytest.raises(ValueError, match="MyLabel"):
        validate_axes_rank(np.zeros((3, 4, 5)), "YX", label="MyLabel")


# ---- validate_axis_order ----

def test_validate_axis_order_accepts_yx() -> None:
    validate_axis_order(np.zeros((4, 5), dtype=np.uint16), "YX")


def test_validate_axis_order_accepts_zyx() -> None:
    validate_axis_order(np.zeros((3, 4, 5), dtype=np.uint16), "ZYX")


def test_validate_axis_order_raises_on_length_mismatch() -> None:
    with pytest.raises(ValueError, match="do not match"):
        validate_axis_order(np.zeros((3, 4, 5), dtype=np.uint16), "YX")


def test_validate_axis_order_raises_when_missing_y() -> None:
    with pytest.raises(ValueError, match="one 'Y'"):
        validate_axis_order(np.zeros((3, 4, 5), dtype=np.uint16), "ZTX")


def test_validate_axis_order_raises_when_missing_x() -> None:
    with pytest.raises(ValueError, match="one 'X'"):
        validate_axis_order(np.zeros((3, 4, 5), dtype=np.uint16), "ZTY")


def test_validate_axis_order_raises_on_duplicate_axes() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_axis_order(np.zeros((3, 4, 5), dtype=np.uint16), "YYX")


def test_validate_axis_order_raises_on_non_array_input() -> None:
    with pytest.raises(ValueError, match="numpy.ndarray"):
        validate_axis_order([1, 2, 3], "Y")  # type: ignore[arg-type]


# ---- validate_channel_count ----

def test_validate_channel_count_accepts_matching_c_axis() -> None:
    validate_channel_count(np.zeros((2, 4, 4)), "CYX", [0, 1])  # should not raise


def test_validate_channel_count_accepts_no_c_axis_with_single_index() -> None:
    validate_channel_count(np.zeros((4, 4)), "YX", [0])  # should not raise


def test_validate_channel_count_raises_on_c_axis_mismatch() -> None:
    with pytest.raises(ValueError, match="channel"):
        validate_channel_count(np.zeros((3, 4, 4)), "CYX", [0, 1])


def test_validate_channel_count_raises_on_no_c_with_multiple_indices() -> None:
    with pytest.raises(ValueError, match="no C axis"):
        validate_channel_count(np.zeros((4, 4)), "YX", [0, 1])


# ---- validate_channel_labels_exist ----

def test_validate_channel_labels_exist_accepts_known_labels() -> None:
    validate_channel_labels_exist(["GFP"], ["GFP", "RFP"], "exclude_channel")


def test_validate_channel_labels_exist_raises_when_labels_missing() -> None:
    with pytest.raises(ValueError, match="Unknown exclude_channel"):
        validate_channel_labels_exist(["DAPI"], ["GFP", "RFP"], "exclude_channel")


def test_validate_channel_labels_exist_raises_when_channel_labels_missing() -> None:
    with pytest.raises(ValueError, match="channel labels are missing"):
        validate_channel_labels_exist(["GFP"], None, "exclude_channel")
