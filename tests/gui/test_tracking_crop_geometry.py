import numpy as np
import pytest

from fits.gui.viewer.tracking.crop_geometry import clip_polyline, fit_track_bounds


def test_automatic_bounds_cover_complete_masks_for_multiple_moving_cells():
    labels = np.zeros((3, 100, 120), dtype=np.uint16)
    labels[0, 20:25, 10:15] = 7
    labels[1, 40:45, 30:35] = 7
    labels[2, 10:15, 70:75] = 7  # A path turn outside the first-to-second box.
    labels[1, 60:65, 80:85] = 11
    labels[:, 1:3, 1:3] = 99  # Unselected cell.
    assert fit_track_bounds(lambda frame: labels[frame], 3, (7, 11)) == (6, 7, 89, 68)


def test_stationary_cell_uses_its_mask_size_and_padding_is_clamped():
    labels = np.zeros((2, 20, 30), dtype=np.uint16)
    labels[:, 0:5, 0:5] = 7
    assert fit_track_bounds(lambda frame: labels[frame], 2, (7,)) == (0, 0, 6, 6)
    assert fit_track_bounds(lambda frame: labels[frame], 2, (7,), lambda: True) is None
    with pytest.raises(ValueError, match="no masks"):
        fit_track_bounds(lambda frame: labels[frame], 2, (999,))


def test_polyline_retains_crossings_with_both_endpoints_outside():
    pieces = clip_polyline(np.array([[-10., 5.], [20., 5.]]), 10, 10)
    assert len(pieces) == 1
    np.testing.assert_allclose(pieces[0], [[0, 5], [10, 5]])


def test_polyline_does_not_join_separate_visible_sections():
    points = np.array([[2., 2.], [20., 2.], [20., 8.], [2., 8.]])
    pieces = clip_polyline(points, 10, 10)
    assert len(pieces) == 2
    np.testing.assert_allclose(pieces[0], [[2, 2], [10, 2]])
    np.testing.assert_allclose(pieces[1], [[10, 8], [2, 8]])


def test_polyline_fully_outside_is_empty():
    assert clip_polyline(np.array([[-10., -5.], [20., -5.]]), 10, 10) == []
