from __future__ import annotations

from pathlib import Path
from typing import Any
import tempfile

import numpy as np
import pytest

from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.provenance import StepProfile
from fits.workflows.tasks.segment import resolve_segment_source_channel_indices, segment_one


class DummyReader:
    def __init__(self, save_path: Path, *, channel_labels: list[str] | None = None, fits_metadata: dict[str, Any] | None = None) -> None:
        self.channel_labels = channel_labels
        self.fits_metadata = fits_metadata or {}
        self.save_path = save_path
        self.save_calls: list[dict[str, Any]] = []

    def save_array(self, array: np.ndarray, **kwargs: Any) -> Path:
        payload = {'array': array}
        payload.update(kwargs)
        self.save_calls.append(payload)
        return self.save_path


class DummyWrapper:
    def __init__(self, segmentation_meta: dict[str, Any], output_axis_order: str = 'YX') -> None:
        self.segmentation_meta = segmentation_meta
        self.output_axis_order = output_axis_order
        self.run_calls: list[tuple[np.ndarray, str]] = []

    def run(self, img: np.ndarray, axis_order: str) -> np.ndarray:
        self.run_calls.append((img, axis_order))
        return np.ones((4, 4), dtype=np.uint16)


def test_resolve_segment_source_channel_indices_maps_exported_labels_to_source_indices() -> None:
    reader = DummyReader(Path('/tmp/fits_mask.tif'), channel_labels=['GFP', 'RFP'], fits_metadata={'source_channel_indices': [1, 2], 'source_channel_count': 3})
    assert resolve_segment_source_channel_indices(reader, ['RFP', 'GFP']) == [2, 1]


def test_resolve_segment_source_channel_indices_requires_source_channel_indices() -> None:
    reader = DummyReader(Path('/tmp/fits_mask.tif'), channel_labels=['GFP', 'RFP'], fits_metadata={})
    with pytest.raises(ValueError, match='source_channel_indices'):
        resolve_segment_source_channel_indices(reader, ['GFP'])


def test_segment_one_writes_channel_aware_metadata(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        input_path = run_dir / 'fits_array.tif'
        input_path.write_bytes(b'')
        state = ExperimentState.init(run_dir, run_dir / 'raw.nd2').with_image(input_path)
        reader = DummyReader(run_dir / 'fits_mask.tif', channel_labels=['GFP', 'RFP'], fits_metadata={'source_channel_indices': [1, 2], 'source_channel_count': 3})
        wrapper = DummyWrapper({'backend': 'v4', 'model_name': 'cpsam'})

        monkeypatch.setattr('fits.workflows.tasks.segment.get_ctx', lambda: type('Ctx', (), {'user_name': 'ben', 'run_dir': run_dir})())
        monkeypatch.setattr('fits.workflows.tasks.segment.FitsIO.from_path', lambda path: reader)
        monkeypatch.setattr('fits.workflows.tasks.segment.get_array', lambda _reader, requested_channels: (np.ones((4, 4), dtype=np.uint16), 'YX'))
        monkeypatch.setattr('fits.workflows.tasks.segment.segment_model_cache.get_wrapper', lambda payload: wrapper)
        monkeypatch.setattr('fits.workflows.tasks.segment.build_fits_payload', lambda step_profile, **kwargs: {'user_name': kwargs['user_name'], 'distribution': step_profile.distribution, 'step_name': step_profile.step_name, 'output_name': kwargs['output_name']})

        out = segment_one(SegmentSettings(channel_to_segment=['RFP'], nuclear_channel=[], user_settings={}), state, StepProfile(distribution='cellpose-kit', step_name='segment'), 'fits_mask.tif')

        assert out.masks == run_dir / 'fits_mask.tif'
        assert out.last_step == 'segment'
        assert len(reader.save_calls) == 1
        assert reader.save_calls[0]['channel_labels'] == ['RFP']
        assert reader.save_calls[0]['custom_metadata'] == {'channels': {'2': {'backend': 'v4', 'model_name': 'cpsam'}}}