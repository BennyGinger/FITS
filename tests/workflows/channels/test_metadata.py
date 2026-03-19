from __future__ import annotations

import pytest

from fits.workflows.channels.metadata import build_channel_metadata, labels_to_src_indices, src_indices_to_labels


class DummyReader:
    def __init__(self, *, channel_labels=None, fits_metadata=None) -> None:
        self.channel_labels = channel_labels
        self.fits_metadata = fits_metadata or {}


def test_labels_to_src_indices_maps_exported_labels() -> None:
    reader = DummyReader(channel_labels=['GFP', 'RFP'], fits_metadata={'source_channel_indices': [3, 7]})

    assert labels_to_src_indices(reader, ['RFP', 'GFP']) == [7, 3]


def test_src_indices_to_labels_maps_back_to_exported_labels() -> None:
    reader = DummyReader(channel_labels=['GFP', 'RFP'], fits_metadata={'source_channel_indices': [3, 7]})

    assert src_indices_to_labels(reader, [7, 3]) == ['RFP', 'GFP']


def test_build_channel_metadata_copies_step_metadata_per_channel() -> None:
    assert build_channel_metadata([1, 4], {'backend': 'v4'}) == {
        'channels': {
            '1': {'backend': 'v4'},
            '4': {'backend': 'v4'},
        }
    }


def test_labels_to_src_indices_requires_consistent_metadata() -> None:
    reader = DummyReader(channel_labels=['GFP'], fits_metadata={'source_channel_indices': [1, 2]})

    with pytest.raises(ValueError, match='metadata mismatch'):
        labels_to_src_indices(reader, ['GFP'])


def test_src_indices_to_labels_rejects_unknown_source_index() -> None:
    reader = DummyReader(channel_labels=['GFP'], fits_metadata={'source_channel_indices': [1]})

    with pytest.raises(ValueError, match='Source index 2'):
        src_indices_to_labels(reader, [2])