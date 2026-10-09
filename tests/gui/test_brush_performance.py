"""Wide brush accuracy and incremental updates (no timing assertions)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from scipy.ndimage import binary_dilation
from skimage.morphology import disk

from fits.gui.viewer.common.image_viewer import FitsImageViewer


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.mark.parametrize("size", [1, 3, 50, 101])
def test_wide_brush_matches_disk_at_edges_and_on_empty_mask(app, size):
    viewer = FitsImageViewer()
    viewer.set_drawing_options("edit", "brush", "add", size)
    selected = np.zeros((128, 160), dtype=bool)
    selected[0, 0] = selected[64, 75] = selected[-1, -1] = True
    expected = binary_dilation(selected, structure=disk(max((size - 1) // 2, 0)))
    np.testing.assert_array_equal(viewer._widen_selection(selected.copy()), expected)
    assert not viewer._widen_selection(np.zeros_like(selected)).any()
    viewer.close()


@pytest.mark.parametrize("operation", ["add", "erase"])
def test_brush_only_rasterizes_new_segments_and_commits_pending_points(app, monkeypatch, operation):
    viewer = FitsImageViewer()
    initial = np.full((160, 160), operation == "erase", dtype=np.uint8)
    viewer.set_drawing_mask(initial)
    viewer.set_drawing_options("edit", "brush", operation, 50)
    calls = []
    original = viewer._brush_selection

    def record(points):
        calls.append(list(points))
        return original(points)

    monkeypatch.setattr(viewer, "_brush_selection", record)
    viewer._start_drawing(30, 30, operation)
    viewer._last_drawing_render = 0
    viewer._continue_drawing(70, 30)
    # Hold the next events until release to exercise throttled input.
    monkeypatch.setattr("fits.gui.viewer.common.image_viewer.DRAWING_REFRESH_SECONDS", float("inf"))
    viewer._continue_drawing(70, 70)
    viewer._finish_drawing(30, 70)
    assert calls == [[(30, 30)], [(30, 30), (30, 70)],
                     [(30, 70), (70, 70), (70, 30)]]
    selected = original([(30, 30), (30, 70), (70, 70), (70, 30)])
    expected = initial.copy()
    expected[selected] = operation == "add"
    np.testing.assert_array_equal(viewer.drawing_mask, expected)
    last_selection = viewer.last_drawing_selection
    assert last_selection is not None
    np.testing.assert_array_equal(last_selection, selected)
    viewer.undo_drawing()
    np.testing.assert_array_equal(viewer.drawing_mask, initial)
    viewer.close()
