from __future__ import annotations

from pathlib import Path
from typing import Any
import tempfile

import numpy as np

from fits.environment.runtime import get_ctx
from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.arrays.mask_output import ProcessMaskOutput
from fits.workflows.metadata.provenance import StepProfile
from fits.workflows.engines.run_decision import RunDecision
from fits.workflows.segment import run_segment, segment_one


class DummyReader:
    def __init__(self, save_path: Path, *, channel_labels: list[str] | None = None, fits_metadata: dict[str, Any] | None = None, axes: list[str] | None = None, array: np.ndarray | None = None) -> None:
        self.channel_labels = channel_labels
        self.fits_metadata = fits_metadata or {}
        self.axes = axes or ['CYX']
        self._array = np.ones((4, 4), dtype=np.uint16) if array is None else array
        self.save_path = save_path
        self.save_calls: list[dict[str, Any]] = []

    def get_array(self) -> np.ndarray:
        return self._array

    def save_array(self, array: np.ndarray, **kwargs: Any) -> Path:
        payload = {'array': array}
        payload.update(kwargs)
        self.save_calls.append(payload)
        self._array = array
        output_name = kwargs.get('output_name')
        if isinstance(output_name, str):
            self.save_path = self.save_path.with_name(output_name)
        return self.save_path


class DummyPbar:
    def __enter__(self) -> DummyPbar:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def advance(self) -> None:
        return None


class DummyWrapper:
    def __init__(self, segmentation_meta: dict[str, Any], output_axis_order: str = 'YX', output_array: np.ndarray | None = None) -> None:
        self.segmentation_meta = segmentation_meta
        self.output_axis_order = output_axis_order
        self.output_array = np.ones((4, 4), dtype=np.uint16) if output_array is None else output_array
        self.run_calls: list[tuple[np.ndarray, str]] = []

    def run(self, img: np.ndarray, axis_order: str) -> np.ndarray:
        self.run_calls.append((img, axis_order))
        return self.output_array


def test_segment_one_returns_error_when_image_is_missing() -> None:
    state = ExperimentState.init(Path('/tmp'), Path('/tmp/raw.nd2'))

    out = segment_one(
        SegmentSettings(channel_to_segment=['RFP'], nuclear_channel=[], user_settings={}, execution='serial'),
        state,
        StepProfile(distribution='cellpose-kit', step_name='segment'),
        'fits_mask.tif',
    )

    assert out.last_error is not None
    assert out.last_error[0] == 'segment'
    assert 'has no image set' in out.last_error[1]


def test_segment_one_saves_mask_for_missing_channels(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        input_path = run_dir / 'fits_array.tif'
        input_path.write_bytes(b'')
        state = ExperimentState.init(run_dir, run_dir / 'raw.nd2').with_image(input_path)
        reader = DummyReader(run_dir / 'fits_mask.tif', channel_labels=['GFP', 'RFP', 'DAPI'], fits_metadata={'fits_io': {'source_channel_indices': [1, 2, 3]}})
        wrapper = DummyWrapper({'backend': 'v4', 'model_name': 'cpsam'})
        captured: dict[str, Any] = {}

        monkeypatch.setattr('fits.workflows.segment.get_ctx', lambda: type('Ctx', (), {'user_name': 'ben', 'run_dir': run_dir})())
        monkeypatch.setattr('fits.workflows.segment.FitsIO.from_path', lambda path: reader)
        monkeypatch.setattr('fits.workflows.segment.decide_run', lambda *args, **kwargs: RunDecision([1, 2], [1], [2]))

        def fake_get_array(_reader: DummyReader, requested_channels: list[str]) -> tuple[np.ndarray, str]:
            captured['requested_channels'] = list(requested_channels)
            return np.ones((4, 4), dtype=np.uint16), 'YX'

        monkeypatch.setattr('fits.workflows.segment.get_array', fake_get_array)
        monkeypatch.setattr('fits.workflows.segment.segment_model_cache.get_wrapper', lambda payload: wrapper)
        monkeypatch.setattr(
            'fits.workflows.segment.prepare_mask_output',
            lambda *args, **kwargs: ProcessMaskOutput(
                array=np.ones((4, 4), dtype=np.uint16),
                axes='YX',
                mask_source_indices=[2],
                channel_labels=['RFP'],
                existing_project_metadata=None,
            ),
        )

        out = segment_one(
            SegmentSettings(channel_to_segment=['GFP', 'RFP'], nuclear_channel=['DAPI'], user_settings={}, execution='serial'),
            state,
            StepProfile(distribution='cellpose-kit', step_name='segment'),
            'fits_mask.tif',
        )

        assert out.masks == run_dir / 'fits_mask.tif'
        assert out.last_step == 'segment'
        assert captured['requested_channels'] == ['RFP', 'DAPI']
        assert len(wrapper.run_calls) == 1
        assert wrapper.run_calls[0][1] == 'YX'
        assert np.array_equal(wrapper.run_calls[0][0], np.ones((4, 4), dtype=np.uint16))
        assert len(reader.save_calls) == 1
        assert reader.save_calls[0]['channel_labels'] == ['RFP']
        project_metadata = reader.save_calls[0]['project_metadata']
        assert project_metadata['pipeline']['user_name'] == 'ben'
        assert project_metadata['pipeline']['distribution'] == 'fits'
        assert 'version' in project_metadata['pipeline']
        assert 'timestamp' in project_metadata['pipeline']
        assert project_metadata['steps']['segment']['distribution'] == 'cellpose-kit'
        assert 'version' in project_metadata['steps']['segment']
        assert 'timestamp' in project_metadata['steps']['segment']
        assert project_metadata['steps']['segment']['mask_source_channel_indices'] == [2]
        assert project_metadata['steps']['segment']['channels'] == {'2': {'backend': 'v4', 'model_name': 'cpsam'}}
        assert 'custom_metadata' not in reader.save_calls[0]
        assert 'user_name' not in reader.save_calls[0]
        assert 'step_name' not in reader.save_calls[0]


def test_segment_one_skips_when_requested_channels_are_complete(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        input_path = run_dir / 'fits_array.tif'
        input_path.write_bytes(b'')
        state = ExperimentState.init(run_dir, run_dir / 'raw.nd2').with_image(input_path)
        reader = DummyReader(input_path, channel_labels=['GFP'], fits_metadata={'fits_io': {'source_channel_indices': [1]}})

        monkeypatch.setattr('fits.workflows.segment.get_ctx', lambda: type('Ctx', (), {'user_name': 'ben', 'run_dir': run_dir})())
        monkeypatch.setattr('fits.workflows.segment.FitsIO.from_path', lambda path: reader)
        monkeypatch.setattr('fits.workflows.segment.decide_run', lambda *args, **kwargs: RunDecision([1], [1], []))
        monkeypatch.setattr(
            'fits.workflows.segment.segment_model_cache.get_wrapper',
            lambda payload: (_ for _ in ()).throw(AssertionError('wrapper should not be created')),
        )

        out = segment_one(
            SegmentSettings(channel_to_segment=['GFP'], nuclear_channel=[], user_settings={}, execution='serial'),
            state,
            StepProfile(distribution='cellpose-kit', step_name='segment'),
            'fits_mask.tif',
        )

        assert out is state
        assert reader.save_calls == []


def test_run_segment_uses_executor_and_worker_context(monkeypatch, DummyCtx_class) -> None:
    states = [ExperimentState.init(Path('/tmp'), Path('/tmp/a.nd2')).with_image(Path('/tmp/fits_array.tif'))]
    step_profile = StepProfile(distribution='cellpose-kit', step_name='segment')
    settings = SegmentSettings(channel_to_segment=['GFP'], nuclear_channel=[], user_settings={}, execution='serial', workers=2, ordered_execution=True)
    seen: dict[str, object] = {}

    monkeypatch.setattr('fits.workflows.segment.get_ctx', lambda: DummyCtx_class(user_name='ben'))
    monkeypatch.setattr('fits.workflows.segment.pbar', lambda **kwargs: DummyPbar())

    def fake_segment_one(settings, exp_state, step_profile, output_name):
        seen['worker_user'] = get_ctx().user_name
        seen['output_name'] = output_name
        return exp_state.with_completed_step(step_profile.step_name)

    monkeypatch.setattr('fits.workflows.segment.segment_one', fake_segment_one)

    def fake_execute(items, worker, *, mode, workers, ordered):
        seen['mode'] = mode
        seen['workers'] = workers
        seen['ordered'] = ordered
        for item in items:
            yield worker(item)

    monkeypatch.setattr('fits.workflows.segment.execute', fake_execute)

    out = run_segment(settings, states, step_profile, 'fits_mask.tif')

    assert seen == {
        'mode': 'serial',
        'workers': 2,
        'ordered': True,
        'worker_user': 'ben',
        'output_name': 'fits_mask.tif',
    }
    assert [state.last_step for state in out] == ['segment']