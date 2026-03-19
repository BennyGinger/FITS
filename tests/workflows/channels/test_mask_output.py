from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fits.workflows.channels.mask_output import merge_step_metadata, prepare_mask_output


class DummyReader:
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
        fits_metadata={'source_channel_indices': [1, 2]},
        axes='CYX',
    )

    out = prepare_mask_output(
        image_reader,
        tmp_path / 'fits_mask.tif',
        np.ones((1, 4, 4), dtype=np.uint16),
        'CYX',
        [2],
    )

    assert out.axes == 'YX'
    assert out.array.shape == (4, 4)
    assert out.mask_source_indices == [2]
    assert out.channel_labels == ['RFP']
    assert out.structural_metadata == {'mask_source_channel_indices': [2]}


def test_merge_step_metadata_preserves_existing_channels(monkeypatch, tmp_path: Path) -> None:
    mask_path = tmp_path / 'fits_mask.tif'
    mask_path.write_bytes(b'')
    existing = DummyReader(fits_metadata={'segment': {'channels': {'1': {'model': 'old'}}, 'legacy': 'keep-me'}})

    monkeypatch.setattr('fits.workflows.channels.mask_output.FitsIO.from_path', lambda path: existing)

    merged = merge_step_metadata(
        mask_path,
        'segment',
        {'channels': {'2': {'model': 'new'}}},
        {'mask_source_channel_indices': [1, 2]},
    )

    assert merged == {
        'channels': {'1': {'model': 'old'}, '2': {'model': 'new'}},
        'legacy': 'keep-me',
        'mask_source_channel_indices': [1, 2],
    }


def test_prepare_mask_output_requires_existing_mask_source_indices(monkeypatch, tmp_path: Path) -> None:
    mask_path = tmp_path / 'fits_mask.tif'
    mask_path.write_bytes(b'')
    image_reader = DummyReader(channel_labels=['GFP'], fits_metadata={'source_channel_indices': [1]})
    existing = DummyReader(fits_metadata={})

    monkeypatch.setattr('fits.workflows.channels.mask_output.FitsIO.from_path', lambda path: existing)

    with pytest.raises(ValueError, match='mask_source_channel_indices'):
        prepare_mask_output(image_reader, mask_path, np.ones((4, 4), dtype=np.uint16), 'YX', [1])