"""Palette lookup must preserve label colours without sorting image pixels."""

import numpy as np
import pytest

from fits.gui.viewer.common.image_viewer import FitsImageViewer, _label_rgba


def test_uint16_palette_matches_existing_colours_without_sorting(monkeypatch):
    labels = np.arange(65536, dtype=np.uint16).reshape(256, 256)
    expected = np.asarray([_label_rgba(int(value)) for value in labels.ravel()],
                          dtype=np.uint8).reshape(256, 256, 4)
    monkeypatch.setattr(np, "unique", lambda *a, **k: pytest.fail("Sorted mask pixels"))
    np.testing.assert_array_equal(FitsImageViewer._colour_mask(labels), expected)


@pytest.mark.parametrize("labels", [
    np.array([[False, True]]),
    np.array([[0, 17, 255]], dtype=np.uint64),
    np.array([[0, -1, 4]], dtype=np.int64),
    np.array([[0, 2**40]], dtype=np.uint64),
    np.array([[0., 1.5, 8.]]),
    np.empty((0, 3), dtype=np.uint16),
])
def test_unusual_label_planes_preserve_colours(labels):
    expected = np.asarray([_label_rgba(int(value)) for value in labels.ravel()],
                          dtype=np.uint8).reshape(*labels.shape, 4)
    np.testing.assert_array_equal(FitsImageViewer._colour_mask(labels), expected)
