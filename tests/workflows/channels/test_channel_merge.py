from __future__ import annotations

import numpy as np
import pytest

from fits.workflows.arrays.channel_merge import _ensure_channel_axis, merge_channel_arrays


# ── ensure_channel_axis ────────────────────────────────────────────────────────

def test_ensure_channel_axis_inserts_c_at_correct_position() -> None:
    arr = np.zeros((3, 4, 5))  # TYX
    result, axes = _ensure_channel_axis(arr, 'TYX', 'TCYX')
    assert axes == 'TCYX'
    assert result.shape == (3, 1, 4, 5)


def test_ensure_channel_axis_inserts_c_at_front_when_no_preceding_dims() -> None:
    arr = np.zeros((4, 5))  # YX, reference has C first
    result, axes = _ensure_channel_axis(arr, 'YX', 'CYX')
    assert axes == 'CYX'
    assert result.shape == (1, 4, 5)


def test_ensure_channel_axis_leaves_unchanged_when_c_already_present() -> None:
    arr = np.zeros((2, 4, 5))  # CYX
    result, axes = _ensure_channel_axis(arr, 'CYX', 'CYX')
    assert axes == 'CYX'
    assert result.shape == (2, 4, 5)


def test_ensure_channel_axis_leaves_unchanged_when_reference_has_no_c() -> None:
    arr = np.zeros((3, 4, 5))  # TYX
    result, axes = _ensure_channel_axis(arr, 'TYX', 'TYX')
    assert axes == 'TYX'
    assert result.shape == (3, 4, 5)


def test_ensure_channel_axis_raises_on_duplicate_axes() -> None:
    arr = np.zeros((2, 4, 5))
    with pytest.raises(ValueError, match='duplicate'):
        _ensure_channel_axis(arr, 'CCY', 'CYX')


def test_ensure_channel_axis_raises_on_axes_rank_mismatch() -> None:
    arr = np.zeros((2, 4, 5))
    with pytest.raises(ValueError, match='do not match array shape'):
        _ensure_channel_axis(arr, 'CY', 'CYX')


# ── merge_channel_arrays: no existing array ────────────────────────────────────

def test_merge_no_existing_returns_normalized_array() -> None:
    arr = np.ones((2, 4, 4), dtype=np.uint16)
    marray, maxes, msrc = merge_channel_arrays(None, None, None, arr, 'CYX', [1, 3], 'CYX')
    assert maxes == 'CYX'
    assert msrc == [1, 3]
    assert marray.shape == (2, 4, 4)


def test_merge_no_existing_sorts_channels_by_source_index() -> None:
    ch_src2 = np.full((4, 4), 2, dtype=np.uint16)
    ch_src0 = np.full((4, 4), 0, dtype=np.uint16)
    arr = np.stack([ch_src2, ch_src0], axis=0)  # C=2, ch[0]=src2, ch[1]=src0
    marray, maxes, msrc = merge_channel_arrays(None, None, None, arr, 'CYX', [2, 0], 'CYX')
    assert msrc == [0, 2]
    assert marray[0, 0, 0] == 0   # src=0 now first
    assert marray[1, 0, 0] == 2   # src=2 now second


def test_merge_no_existing_inserts_c_for_squeezed_input() -> None:
    arr = np.ones((4, 4), dtype=np.uint16)  # YX, no C
    marray, maxes, msrc = merge_channel_arrays(None, None, None, arr, 'YX', [0], 'CYX')
    assert maxes == 'CYX'
    assert msrc == [0]
    assert marray.shape == (1, 4, 4)


# ── merge_channel_arrays: append new channel ──────────────────────────────────

def test_merge_appends_new_channel_to_existing() -> None:
    gfp = np.full((1, 4, 4), 1, dtype=np.uint16)  # CYX, src=0
    rfp = np.full((1, 4, 4), 2, dtype=np.uint16)  # CYX, src=2
    marray, maxes, msrc = merge_channel_arrays(gfp, 'CYX', [0], rfp, 'CYX', [2], 'CYX')
    assert msrc == [0, 2]
    assert maxes == 'CYX'
    assert marray.shape == (2, 4, 4)
    assert marray[0, 0, 0] == 1   # GFP preserved
    assert marray[1, 0, 0] == 2   # RFP appended


def test_merge_appends_preserves_channel_ordering_by_source_index() -> None:
    rfp = np.full((1, 4, 4), 2, dtype=np.uint16)  # src=5 (high index)
    gfp = np.full((1, 4, 4), 1, dtype=np.uint16)  # src=1 (low index)
    # merge rfp first, then gfp — output should be sorted [1, 5]
    mid, _, msrc_mid = merge_channel_arrays(None, None, None, rfp, 'CYX', [5], 'CYX')
    marray, maxes, msrc = merge_channel_arrays(mid, 'CYX', msrc_mid, gfp, 'CYX', [1], 'CYX')
    assert msrc == [1, 5]
    assert marray[0, 0, 0] == 1   # src=1 (GFP) is first
    assert marray[1, 0, 0] == 2   # src=5 (RFP) is second


# ── merge_channel_arrays: replace existing channel ────────────────────────────

def test_merge_replaces_existing_channel_with_recomputed_version() -> None:
    old = np.full((1, 4, 4), 99, dtype=np.uint16)
    new = np.full((1, 4, 4), 1, dtype=np.uint16)
    marray, maxes, msrc = merge_channel_arrays(old, 'CYX', [0], new, 'CYX', [0], 'CYX')
    assert msrc == [0]
    assert marray.shape == (1, 4, 4)
    assert marray[0, 0, 0] == 1   # old value replaced


def test_merge_replaces_one_channel_preserves_others() -> None:
    existing = np.stack([np.full((4, 4), 10), np.full((4, 4), 20)], axis=0).astype(np.uint16)
    recomputed_gfp = np.full((1, 4, 4), 99, dtype=np.uint16)
    marray, maxes, msrc = merge_channel_arrays(existing, 'CYX', [0, 2], recomputed_gfp, 'CYX', [0], 'CYX')
    assert msrc == [0, 2]
    assert marray.shape == (2, 4, 4)
    assert marray[0, 0, 0] == 99  # recomputed GFP
    assert marray[1, 0, 0] == 20  # RFP unchanged


# ── merge_channel_arrays: axis handling ────────────────────────────────────────

def test_merge_raises_on_different_axis_orderings() -> None:
    # Different order is no longer canonicalized; it must fail fast.
    existing = np.stack([np.full((4, 4), 10), np.full((4, 4), 20)], axis=0).astype(np.uint16)  # CYX, src=[0,2]
    new_arr = np.full((4, 1, 4), 99, dtype=np.uint16)  # YCX, src=[2]
    with pytest.raises(ValueError, match='axes ordering'):
        merge_channel_arrays(existing, 'CYX', [0, 2], new_arr, 'YCX', [2], 'CYX')


def test_merge_handles_squeezed_new_against_existing_with_time() -> None:
    # existing has T axis, new is squeezed (no C)
    existing = np.full((3, 1, 4, 4), 10, dtype=np.uint16)  # TCYX, T=3, C=1
    new_arr = np.full((3, 4, 4), 20, dtype=np.uint16)       # TYX, squeezed
    marray, maxes, msrc = merge_channel_arrays(existing, 'TCYX', [1], new_arr, 'TYX', [3], 'TCYX')
    assert maxes == 'TCYX'
    assert msrc == [1, 3]
    assert marray.shape == (3, 2, 4, 4)
    assert marray[0, 0, 0, 0] == 10   # src=1 preserved
    assert marray[0, 1, 0, 0] == 20   # src=3 appended


# ── merge_channel_arrays: error cases ─────────────────────────────────────────

def test_merge_raises_on_incompatible_spatial_shapes() -> None:
    existing = np.ones((1, 4, 4), dtype=np.uint16)
    new_arr = np.ones((1, 6, 8), dtype=np.uint16)
    with pytest.raises(ValueError, match='[Ii]ncompatible|shapes'):
        merge_channel_arrays(existing, 'CYX', [0], new_arr, 'CYX', [1], 'CYX')


def test_merge_raises_when_existing_channel_count_mismatches_indices() -> None:
    existing = np.ones((3, 4, 4), dtype=np.uint16)  # C=3 but only 1 source index
    new_arr = np.ones((1, 4, 4), dtype=np.uint16)
    with pytest.raises(ValueError, match='channel'):
        merge_channel_arrays(existing, 'CYX', [0], new_arr, 'CYX', [1], 'CYX')


def test_merge_raises_when_new_channel_count_mismatches_indices() -> None:
    new_arr = np.ones((2, 4, 4), dtype=np.uint16)  # C=2 but 3 source indices
    with pytest.raises(ValueError, match='channel'):
        merge_channel_arrays(None, None, None, new_arr, 'CYX', [0, 1, 2], 'CYX')


def test_merge_raises_on_empty_new_source_indices() -> None:
    new_arr = np.ones((4, 4), dtype=np.uint16)
    with pytest.raises(ValueError, match='empty'):
        merge_channel_arrays(None, None, None, new_arr, 'YX', [], 'CYX')


def test_merge_raises_when_existing_provided_without_axes() -> None:
    existing = np.ones((1, 4, 4), dtype=np.uint16)
    new_arr = np.ones((1, 4, 4), dtype=np.uint16)
    with pytest.raises(ValueError, match='existing_axes'):
        merge_channel_arrays(existing, None, [0], new_arr, 'CYX', [1], 'CYX')


def test_merge_raises_on_dimensionality_mismatch_after_normalization() -> None:
    existing = np.ones((1, 1, 4, 4), dtype=np.uint16)  # malformed for CYX on purpose
    new_arr = np.ones((1, 4, 4), dtype=np.uint16)      # CYX
    with pytest.raises(ValueError, match='do not match array shape'):
        merge_channel_arrays(existing, 'CYX', [0], new_arr, 'CYX', [1], 'CYX')
