from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import pytest

from fits_io.client import FitsIO

from fits.workflows.arrays.mask_output import prepare_mask_output


class DummyReader():
    def __init__(self, *, channel_labels=None, fits_metadata=None, axes='CYX', array=None) -> None:
        self.channel_labels = channel_labels
        self.fits_metadata = fits_metadata or {}
        self.axes = [axes]
        self._array = np.ones((1, 4, 4), dtype=np.uint16) if array is None else array

    def get_array(self):
        return self._array


def test_prepare_mask_output_squeezes_singleton_channel_axis(tmp_path: Path) -> None:
    image_reader = DummyReader(
        channel_labels=['GFP', 'RFP'],
        fits_metadata={'fits_io': {'source_channel_indices': [1, 2]}},
        axes='CYX',
    )

    out = prepare_mask_output(
        cast(FitsIO, image_reader),
        tmp_path / 'fits_mask.tif',
        np.ones((1, 4, 4), dtype=np.uint16),
        'CYX',
        [2],
        'segment',
    )

    assert out.axes == 'YX'
    assert out.array.shape == (4, 4)
    assert out.mask_source_indices == [2]
    assert out.channel_labels == ['RFP']
    assert out.existing_project_metadata is None


def test_prepare_mask_output_merges_existing_channels(monkeypatch, tmp_path: Path) -> None:
    mask_path = tmp_path / 'fits_mask.tif'
    mask_path.write_bytes(b'')
    existing = DummyReader(
        fits_metadata={
            'project_metadata': {
                'steps': {
                    'segment': {
                        'mask_source_channel_indices': [1],
                    }
                }
            }
        },
        axes='YX',
        array=np.ones((4, 4), dtype=np.uint16),
    )
    image_reader = DummyReader(channel_labels=['GFP', 'RFP'], fits_metadata={'fits_io': {'source_channel_indices': [1, 2]}}, axes='CYX')

    monkeypatch.setattr('fits.workflows.arrays.mask_output.FitsIO.from_path', lambda path: existing)

    merged = prepare_mask_output(
        cast(FitsIO, image_reader),
        mask_path,
        np.ones((4, 4), dtype=np.uint16),
        'YX',
        [2],
        'segment',
    )

    assert merged.axes == 'CYX'
    assert merged.array.shape == (2, 4, 4)
    assert merged.mask_source_indices == [1, 2]
    assert merged.channel_labels == ['GFP', 'RFP']
    assert merged.existing_project_metadata == {
        'steps': {
            'segment': {
                'mask_source_channel_indices': [1],
            }
        }
    }


def test_prepare_mask_output_requires_existing_mask_source_indices(monkeypatch, tmp_path: Path) -> None:
    mask_path = tmp_path / 'fits_mask.tif'
    mask_path.write_bytes(b'')
    image_reader = DummyReader(channel_labels=['GFP'], fits_metadata={'fits_io': {'source_channel_indices': [1]}})
    existing = DummyReader(fits_metadata={})

    monkeypatch.setattr('fits.workflows.arrays.mask_output.FitsIO.from_path', lambda path: existing)

    with pytest.raises(ValueError, match='mask_source_channel_indices'):
        prepare_mask_output(cast(FitsIO, image_reader), mask_path, np.ones((4, 4), dtype=np.uint16), 'YX', [1], 'segment')


def test_prepare_mask_output_overwrite_ignores_stale_existing_mask(monkeypatch, tmp_path: Path) -> None:
    mask_path = tmp_path / 'fits_mask.tif'
    mask_path.write_bytes(b'')
    image_reader = DummyReader(channel_labels=['GFP'], fits_metadata={'fits_io': {'source_channel_indices': [1]}}, axes='CYX')
    stale_existing = DummyReader(fits_metadata={}, axes='YX', array=np.ones((4, 4), dtype=np.uint16))

    monkeypatch.setattr('fits.workflows.arrays.mask_output.FitsIO.from_path', lambda path: stale_existing)

    out = prepare_mask_output(
        cast(FitsIO, image_reader),
        mask_path,
        np.ones((4, 4), dtype=np.uint16),
        'YX',
        [1],
        'segment',
        overwrite=True,
    )

    assert out.mask_source_indices == [1]
    assert out.channel_labels == ['GFP']