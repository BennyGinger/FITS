from __future__ import annotations

import numpy as np
import pytest
from typing import cast

from fits_io.client import FitsIO
from fits.workflows.arrays.loading import get_array


class DummyReader:
    def __init__(self, *, channel_labels, axes, array, subset_array) -> None:
        self.channel_labels = channel_labels
        self.axes = [axes]
        self._array = array
        self._subset_array = subset_array
        self.requested_channels: list[list[str]] = []

    def get_array(self):
        return self._array

    def get_channel_array(self, channels: list[str]):
        self.requested_channels.append(list(channels))
        return self._subset_array


def test_get_array_returns_full_array_when_all_channels_requested() -> None:
    reader = DummyReader(
        channel_labels=['GFP', 'RFP'],
        axes='CYX',
        array=np.ones((2, 4, 4), dtype=np.uint16),
        subset_array=np.ones((4, 4), dtype=np.uint16),
    )

    array, axes = get_array(cast(FitsIO, reader), ['RFP', 'GFP'])

    assert axes == 'CYX'
    assert array.shape == (2, 4, 4)
    assert reader.requested_channels == []


def test_get_array_returns_full_array_when_requested_channels_is_default() -> None:
    reader = DummyReader(
        channel_labels=['GFP', 'RFP'],
        axes='CYX',
        array=np.ones((2, 4, 4), dtype=np.uint16),
        subset_array=np.ones((4, 4), dtype=np.uint16),
    )

    array, axes = get_array(cast(FitsIO, reader))

    assert axes == 'CYX'
    assert array.shape == (2, 4, 4)
    assert reader.requested_channels == []


def test_get_array_returns_full_array_when_requested_channels_is_all_sequence() -> None:
    reader = DummyReader(
        channel_labels=['GFP', 'RFP'],
        axes='CYX',
        array=np.ones((2, 4, 4), dtype=np.uint16),
        subset_array=np.ones((4, 4), dtype=np.uint16),
    )

    array, axes = get_array(cast(FitsIO, reader), ['all'])

    assert axes == 'CYX'
    assert array.shape == (2, 4, 4)
    assert reader.requested_channels == []


def test_get_array_drops_c_axis_for_single_subset_channel() -> None:
    reader = DummyReader(
        channel_labels=['GFP', 'RFP'],
        axes='CYX',
        array=np.ones((2, 4, 4), dtype=np.uint16),
        subset_array=np.full((4, 4), 7, dtype=np.uint16),
    )

    array, axes = get_array(cast(FitsIO, reader), ['RFP'])

    assert axes == 'YX'
    assert array.shape == (4, 4)
    assert reader.requested_channels == [['RFP']]


def test_get_array_requires_channel_labels() -> None:
    reader = DummyReader(channel_labels=None, axes='CYX', array=np.ones((2, 4, 4)), subset_array=np.ones((4, 4)))

    with pytest.raises(ValueError, match='channel labels'):
        get_array(cast(FitsIO, reader), ['GFP'])


def test_get_array_with_all_sequence_does_not_require_channel_labels() -> None:
    reader = DummyReader(channel_labels=None, axes='CYX', array=np.ones((2, 4, 4)), subset_array=np.ones((4, 4)))

    array, axes = get_array(cast(FitsIO, reader), ['all'])

    assert axes == 'CYX'
    assert array.shape == (2, 4, 4)


def test_get_array_rejects_multi_series_results() -> None:
    reader = DummyReader(
        channel_labels=['GFP', 'RFP'],
        axes='CYX',
        array=[np.ones((2, 4, 4), dtype=np.uint16)],
        subset_array=np.ones((4, 4), dtype=np.uint16),
    )

    with pytest.raises(ValueError, match='multi-series'):
        get_array(cast(FitsIO, reader), ['GFP', 'RFP'])