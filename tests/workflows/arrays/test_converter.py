from __future__ import annotations

import numpy as np
import pytest

from fits.workflows.arrays.converter import flatten_to_frames


# ---- flatten_to_frames ----

@pytest.mark.parametrize(
    ('shape', 'axis_order', 'expected_frames'),
    [
        ((4, 5), 'YX', 1),
        ((2, 4, 5), 'ZYX', 2),
        ((3, 4, 5), 'TYX', 3),
        ((2, 3, 4, 5), 'CZYX', 6),
        ((2, 3, 4, 5, 6), 'TCZYX', 24),
    ],
)
def test_flatten_to_frames_expected_counts_and_frame_shape(shape: tuple[int, ...], axis_order: str, expected_frames: int) -> None:
    arr = np.arange(np.prod(shape), dtype=np.int32).reshape(shape)

    batch = flatten_to_frames(arr, axis_order)

    assert len(batch.frames) == expected_frames
    assert all(frame.shape == (shape[-2], shape[-1]) for frame in batch.frames)


def test_flatten_to_frames_yx_metadata_is_correct() -> None:
    arr = np.arange(20, dtype=np.int16).reshape(4, 5)

    batch = flatten_to_frames(arr, 'YX')

    assert batch.axis_order == 'YX'
    assert batch.original_shape == (4, 5)
    assert batch.moved_shape == (4, 5)
    assert batch.batch_shape == ()
    assert batch.yx_shape == (4, 5)
    assert batch.spatial_indices == (0, 1)
    assert len(batch.frames) == 1
    assert np.array_equal(batch.frames[0], arr)


def test_flatten_to_frames_tczyx_metadata_is_correct() -> None:
    arr = np.arange(2 * 3 * 4 * 5 * 6, dtype=np.int32).reshape(2, 3, 4, 5, 6)

    batch = flatten_to_frames(arr, 'TCZYX')

    assert batch.axis_order == 'TCZYX'
    assert batch.original_shape == (2, 3, 4, 5, 6)
    assert batch.moved_shape == (2, 3, 4, 5, 6)
    assert batch.batch_shape == (2, 3, 4)
    assert batch.yx_shape == (5, 6)
    assert batch.spatial_indices == (3, 4)
    assert len(batch.frames) == 24
    assert all(frame.shape == (5, 6) for frame in batch.frames)


# ---- rebuild_from_frames ----

@pytest.mark.parametrize(
    ('shape', 'axis_order'),
    [
        ((4, 5), 'YX'),
        ((2, 4, 5), 'ZYX'),
        ((3, 4, 5), 'TYX'),
        ((2, 3, 4, 5), 'CZYX'),
        ((2, 3, 4, 5, 6), 'TCZYX'),
    ],
)
def test_roundtrip_flatten_then_rebuild_preserves_shape_and_values(shape: tuple[int, ...], axis_order: str) -> None:
    original = np.arange(np.prod(shape), dtype=np.int64).reshape(shape)

    batch = flatten_to_frames(original, axis_order)
    rebuilt = batch.rebuild(batch.frames)

    assert rebuilt.shape == original.shape
    assert np.array_equal(rebuilt, original)


def test_rebuild_from_frames_raises_on_wrong_frame_count() -> None:
    arr = np.arange(2 * 4 * 5, dtype=np.int32).reshape(2, 4, 5)
    batch = flatten_to_frames(arr, 'ZYX')

    with pytest.raises(ValueError, match='Expected 2 frame'):
        batch.rebuild(batch.frames[:1])


def test_rebuild_from_frames_raises_on_wrong_frame_shape() -> None:
    arr = np.arange(2 * 4 * 5, dtype=np.int32).reshape(2, 4, 5)
    batch = flatten_to_frames(arr, 'ZYX')
    bad_frames = [batch.frames[0], np.zeros((3, 5), dtype=np.int32)]

    with pytest.raises(ValueError, match='expected'):
        batch.rebuild(bad_frames)


def test_rebuild_from_frames_raises_on_non_array_frame() -> None:
    arr = np.arange(2 * 4 * 5, dtype=np.int32).reshape(2, 4, 5)
    batch = flatten_to_frames(arr, 'ZYX')
    bad_frames = [batch.frames[0], [[1, 2], [3, 4]]]  # type: ignore[list-item]

    with pytest.raises(ValueError, match='numpy.ndarray'):
        batch.rebuild(bad_frames)


def test_tczyx_integration_like_roundtrip() -> None:
    original = np.arange(2 * 2 * 3 * 4 * 5, dtype=np.uint16).reshape(2, 2, 3, 4, 5)

    batch = flatten_to_frames(original, 'TCZYX')
    rebuilt = batch.rebuild(batch.frames)

    assert np.array_equal(rebuilt, original)