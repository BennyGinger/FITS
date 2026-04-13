from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from fits.environment.state import ExperimentState
from fits.workflows.engines.run_decision import RunDecision, decide_run


class _DummyReader:
    def __init__(self, fits_metadata: dict[str, object]) -> None:
        self.fits_metadata = fits_metadata


def test_build_completion_plan_step_mode_overwrite_never_skips() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / 'fits_array.tif'
        image_path.write_bytes(b'')
        state = ExperimentState.init(run_dir, run_dir / 'raw.nd2').with_image(image_path).with_completed_step('convert')
        plan = decide_run(state, 'convert', overwrite=True)
        assert plan == RunDecision(requested_items=['convert'], completed_items=[], missing_items=['convert'])
        assert plan.is_complete is False


def test_build_completion_plan_step_mode_completed_and_image_exists_skips() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / 'fits_array.tif'
        image_path.write_bytes(b'')
        state = ExperimentState.init(run_dir, run_dir / 'raw.nd2').with_image(image_path).with_completed_step('convert')
        plan = decide_run(state, 'convert', overwrite=False)
        assert plan == RunDecision(requested_items=['convert'], completed_items=['convert'], missing_items=[])
        assert plan.is_complete is True


def test_build_completion_plan_mask_mode_no_mask_file_all_pending() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / 'fits_array.tif'
        image_path.write_bytes(b'')
        state = ExperimentState.init(run_dir, run_dir / 'raw.nd2').with_image(image_path).with_masks(run_dir / 'fits_mask.tif')
        plan = decide_run(state, 'segment', overwrite=False, requested_items=[1, 2])
        assert plan == RunDecision(requested_items=[1, 2], completed_items=[], missing_items=[1, 2])
        assert plan.is_complete is False


def test_build_completion_plan_mask_mode_partial_coverage(monkeypatch, tmp_path: Path) -> None:
    mask_path = tmp_path / 'mask.tif'
    mask_path.write_bytes(b'')
    image_path = tmp_path / 'image.tif'
    image_path.write_bytes(b'')
    state = ExperimentState.init(tmp_path, tmp_path / 'raw.nd2').with_image(image_path).with_masks(mask_path)
    monkeypatch.setattr(
        'fits.workflows.engines.run_decision.FitsIO.from_path',
        lambda p: _DummyReader({'project_metadata': {'steps': {'segment': {'mask_source_channel_indices': [1]}}}}),
    )
    plan = decide_run(state, 'segment', overwrite=False, requested_items=[1, 2])
    assert plan == RunDecision(requested_items=[1, 2], completed_items=[1], missing_items=[2])
    assert plan.is_complete is False


def test_build_completion_plan_mask_mode_overwrite_forces_pending(monkeypatch, tmp_path: Path) -> None:
    mask_path = tmp_path / 'mask.tif'
    mask_path.write_bytes(b'')
    image_path = tmp_path / 'image.tif'
    image_path.write_bytes(b'')
    state = ExperimentState.init(tmp_path, tmp_path / 'raw.nd2').with_image(image_path).with_masks(mask_path)
    monkeypatch.setattr(
        'fits.workflows.engines.run_decision.FitsIO.from_path',
        lambda p: _DummyReader({'project_metadata': {'steps': {'segment': {'mask_source_channel_indices': [1, 2]}}}}),
    )
    plan = decide_run(state, 'segment', overwrite=True, requested_items=[1, 2])
    assert plan == RunDecision(requested_items=[1, 2], completed_items=[], missing_items=[1, 2])
    assert plan.is_complete is False


def test_build_completion_plan_mask_mode_missing_metadata_raises(monkeypatch, tmp_path: Path) -> None:
    mask_path = tmp_path / 'mask.tif'
    mask_path.write_bytes(b'')
    image_path = tmp_path / 'image.tif'
    image_path.write_bytes(b'')
    state = ExperimentState.init(tmp_path, tmp_path / 'raw.nd2').with_image(image_path).with_masks(mask_path)
    monkeypatch.setattr('fits.workflows.engines.run_decision.FitsIO.from_path', lambda p: _DummyReader({}))
    with pytest.raises(ValueError, match='mask_source_channel_indices'):
        decide_run(state, 'segment', overwrite=False, requested_items=[1])