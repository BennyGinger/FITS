from __future__ import annotations

import numpy as np
import pytest

from fits.tasks.tracking.static_masks import process_static_masks


def _square(top: int, left: int, *, size: int = 3, label: int = 1) -> np.ndarray:
    mask = np.zeros((12, 12), dtype=np.uint16)
    mask[top:top + size, left:left + size] = label
    return mask


def test_process_removes_shape_outlier_and_interpolates_its_frame() -> None:
    masks = np.stack([_square(3, 3) for _ in range(5)])
    masks[2] = _square(1, 1, size=8)
    original = masks.copy()
    result = process_static_masks(
        masks,
        shape_similarity=0.8,
        minimum_appearances=3,
        extrapolate_start=False,
        extrapolate_end=False,
    )

    np.testing.assert_array_equal(result, np.stack([_square(3, 3) for _ in range(5)]))
    np.testing.assert_array_equal(masks, original)


def test_process_discards_track_with_too_few_trustworthy_masks() -> None:
    masks = np.zeros((5, 12, 12), dtype=np.uint16)
    masks[1] = _square(3, 3, label=7)
    masks[3] = _square(3, 3, label=7)
    result = process_static_masks(masks, minimum_appearances=3)

    assert not np.any(result)


def test_process_can_leave_track_endpoints_empty() -> None:
    masks = np.zeros((5, 12, 12), dtype=np.uint16)
    masks[1:4] = np.stack([_square(3, 3, label=4) for _ in range(3)])
    result = process_static_masks(
        masks,
        minimum_appearances=3,
        extrapolate_start=False,
        extrapolate_end=False,
    )

    assert not np.any(result[0])
    assert not np.any(result[4])
    np.testing.assert_array_equal(result[1:4], masks[1:4])


def test_process_preserves_labels_shape_and_dtype() -> None:
    masks = np.zeros((4, 12, 12), dtype=np.uint16)
    masks[(0, 1, 3), 2:5, 2:5] = 2
    masks[(0, 2, 3), 7:10, 7:10] = 9
    result = process_static_masks(masks, minimum_appearances=3)

    assert result.shape == masks.shape
    assert result.dtype == masks.dtype
    assert set(np.unique(result)) == {0, 2, 9}
    assert np.all(np.any(result == 2, axis=(1, 2)))
    assert np.all(np.any(result == 9, axis=(1, 2)))


def test_completion_uses_supermask_on_overlap_without_leaving_halo() -> None:
    masks = np.zeros((3, 12, 12), dtype=np.uint16)
    masks[:, 3:6, 3:6] = 9
    masks[0, 3:6, 0:3] = 2
    masks[2, 3:6, 6:9] = 2
    result = process_static_masks(
        masks,
        shape_similarity=0,
        minimum_appearances=1,
    )

    np.testing.assert_array_equal(result[:, 3:6, 3:6], 9)
    assert np.all(np.any(result == 2, axis=(1, 2)))
    assert not np.any((result == 2)[:, 3:6, 3:6])


@pytest.mark.parametrize("masks", [
    np.zeros((3, 8), dtype=np.uint16),
    np.zeros((3, 8, 8), dtype=np.float32),
])
def test_process_rejects_invalid_arrays(masks: np.ndarray) -> None:
    with pytest.raises((TypeError, ValueError)):
        process_static_masks(masks)


@pytest.mark.parametrize("extend_start,extend_end", [(True, True), (False, False),
                                                    (True, False), (False, True)])
def test_reconnects_static_identity_change_and_completes_gaps(
    extend_start: bool, extend_end: bool,
) -> None:
    masks = np.zeros((20, 12, 12), dtype=np.uint16)
    masks[2:5] = _square(3, 3, label=16)
    masks[15:18] = _square(3, 3, label=48)
    original = masks.copy()
    result = process_static_masks(
        masks,
        minimum_appearances=5,
        extrapolate_start=extend_start,
        extrapolate_end=extend_end,
    )

    expected = np.zeros_like(masks)
    expected[0 if extend_start else 2:20 if extend_end else 18] = _square(
        3, 3, label=16)
    np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(masks, original)


def test_reconnection_preserves_distinct_static_positions() -> None:
    masks = np.zeros((8, 12, 12), dtype=np.uint16)
    masks[:4] = _square(1, 1, label=16)
    masks[4:] = _square(7, 7, label=48)
    result = process_static_masks(masks, minimum_appearances=4)
    assert np.all(np.any(result == 16, axis=(1, 2)))
    assert np.all(np.any(result == 48, axis=(1, 2)))
