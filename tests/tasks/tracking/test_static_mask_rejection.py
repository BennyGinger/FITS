"""Doubtful observations become gaps; collision fragments cannot complete tracks."""

import numpy as np
import pytest

from fisch.tasks.tracking.static_masks import process_static_masks
from fisch.tasks.tracking.static_masks.completion import complete_tracks
from fisch.tasks.tracking.static_masks.identities import reconnect_identities


def test_reconnection_clears_weak_ambiguous_and_unmatched_observations() -> None:
    """
    Keep doubtful shapes empty instead of retaining their original tracking labels.
    """
    reference = np.zeros((16, 20), dtype=np.uint16)
    reference[2:6, 2:6] = 7
    reference[2:6, 10:14] = 27
    masks = np.zeros((4, 16, 20), dtype=np.uint16)
    masks[0, 2, 2] = 99
    masks[1, reference > 0] = 99
    masks[2, 12:15, 12:15] = 99
    masks[3, reference == 7] = 99
    original = masks.copy()
    result = reconnect_identities(masks, reference)
    assert not np.any(result[:3])
    np.testing.assert_array_equal(result[3], np.where(reference == 7, 7, 0))
    np.testing.assert_array_equal(masks, original)


@pytest.mark.parametrize("second_cell_observed", [False, True])
def test_merged_observations_are_rejected_before_warping_cell_seven(second_cell_observed: bool) -> None:
    """
    Reproduce the cell-7/27 failure without requiring a tracking model or real data.
    """
    masks = np.zeros((11, 32, 48), dtype=np.uint16)
    cell = np.zeros((32, 48), dtype=bool)
    cell[10:16, 30:36] = True
    other = np.zeros_like(cell)
    other[10:16, 10:16] = True
    merged = cell | other
    merged[10, 30] = False
    for frame in (0, 1, 2, 8, 9, 10):
        masks[frame, cell] = 7
        if second_cell_observed:
            masks[frame, other] = 27
    masks[3:8, merged] = 27
    original = masks.copy()
    result = process_static_masks(masks, shape_similarity=0.9, minimum_appearances=5)
    expected = np.zeros_like(masks)
    expected[:, cell] = 7
    if second_cell_observed:
        expected[:, other] = 27
    np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(masks, original)


@pytest.mark.parametrize("remaining_pixels", [0, 1, 2])
def test_completion_rejects_severely_clipped_reconstruction(remaining_pixels: int) -> None:
    """
    Treat empty and tiny clipped masks as failed completion, preserving other cells.
    """
    filtered = np.zeros((3, 12, 12), dtype=np.uint16)
    filtered[0, 3:9, 3:9] = filtered[2, 3:9, 3:9] = 7
    filtered[1, 3:9, 3:9] = 27
    filtered[1, 3, 3:3 + remaining_pixels] = 0
    original = filtered.copy()
    result = complete_tracks(filtered, extrapolate_start=False, extrapolate_end=False)
    assert not np.any(result == 7)
    np.testing.assert_array_equal(result[1], original[1])
    np.testing.assert_array_equal(filtered, original)


def test_completion_allows_minor_collision_clipping() -> None:
    """
    Retain a usable reconstruction when only one of its 36 pixels is occupied.
    """
    filtered = np.zeros((3, 12, 12), dtype=np.uint16)
    filtered[0, 3:9, 3:9] = filtered[2, 3:9, 3:9] = 7
    filtered[1, 3, 3] = 27
    result = complete_tracks(filtered, extrapolate_start=False, extrapolate_end=False)
    assert np.count_nonzero(result[1] == 7) == 35
    assert result[1, 3, 3] == 27
    np.testing.assert_array_equal(result[[0, 2]], filtered[[0, 2]])


@pytest.mark.parametrize("minimum_iou, retained", [(0.5, True), (0.9, False)])
def test_completion_applies_configured_collision_quality(minimum_iou: float, retained: bool) -> None:
    """
    Reject moderate collision damage when a stricter reconstruction quality is required.
    """
    filtered = np.zeros((3, 12, 12), dtype=np.uint16)
    filtered[0, 3:9, 3:9] = filtered[2, 3:9, 3:9] = 7
    filtered[1, 3:5, 3:9] = 27
    result = complete_tracks(filtered,
                             extrapolate_start=False,
                             extrapolate_end=False,
                             minimum_iou=minimum_iou,
                             )
    assert bool(np.any(result == 7)) is retained
    np.testing.assert_array_equal(result[1] == 27, filtered[1] == 27)
