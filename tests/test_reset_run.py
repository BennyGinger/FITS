"""Irreversible reset preserves acquisitions and rejects unsafe runs before deletion."""

import json
from pathlib import Path

import pytest
from fits.environment import constant as cst
from fits.workflows.experiments import ExperimentState, save_experiment_state
from fits.workflows.file_management.reset import plan_reset, reset_run
from fits.channel_labels.lock import run_write_guard


def _portable_run(root: Path) -> Path:
    """
    Create two series sharing an acquisition, with generated data and backup history.
    """
    acquisition = root / 'control/sample'
    acquisition.mkdir(parents=True)
    original = acquisition / 'sample.nd2'
    original.write_bytes(b'original acquisition bytes')
    for name in ('sample_s1', 'sample_s2'):
        series = acquisition / name
        series.mkdir()
        image = series / cst.FITS_ARRAY_RAW
        image.write_bytes(b'generated pixels')
        state = ExperimentState.init(series, original).with_complete_step(
            step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=image)
        save_experiment_state(state)
        for output in ('fits_masks_track.tif', 'fits_ref_Cell.tif', 'fits_roi_Cell.tif',
                       'fits_masks_track_cyto.tif', 'fits_quantification.parquet', 'fits_track_overlay.png',
                       '.fits_masks_track.tif.centroids-c0-z0.npz'):
            (series / output).write_bytes(b'output')
    for relative in ('.fits/backup/history/original.nd2', '.fits/logs/fits.log', '.fits/fits_settings.toml',
                     'control/sample/.fits_experiment/cache/preview.npy'):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'internal data')
    (root / cst.MASTER_QUANTI_NAME).write_bytes(b'master')
    return original


def test_reset_restores_shared_raw_and_removes_all_generated_data(tmp_path: Path) -> None:
    """
    Reset both series and history together, preserving raw bytes and unrelated files.
    """
    original = _portable_run(tmp_path)
    before = original.read_bytes()
    unrelated = original.parent / 'sample_s1/notes.txt'
    unrelated.write_text('keep me')
    reset_run(tmp_path)
    assert (tmp_path / 'control/sample.nd2').read_bytes() == before
    assert unrelated.read_text() == 'keep me'
    assert not original.exists()
    assert {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob('*') if path.is_file()} == {
        'control/sample.nd2', 'control/sample/sample_s1/notes.txt'}
    reset_run(tmp_path)
    assert (tmp_path / 'control/sample.nd2').read_bytes() == before


@pytest.mark.parametrize('problem', ['collision', 'missing', 'corrupt', 'external_link'])
def test_reset_rejects_unsafe_inputs_before_mutation(tmp_path: Path, problem: str) -> None:
    """
    Invalid original references and destinations never delete generated files or history.
    """
    original = _portable_run(tmp_path)
    if problem == 'collision':
        (tmp_path / 'control/sample.nd2').write_bytes(b'different raw')
    elif problem == 'missing':
        original.unlink()
    elif problem == 'corrupt':
        state = next(tmp_path.rglob('experiment_state.json'))
        state.write_text('{bad json')
    else:
        original.unlink()
        original.symlink_to('/etc/hosts')
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    with pytest.raises((ValueError, OSError)):
        reset_run(tmp_path)
    assert {path: path.read_bytes() for path in before} == before


def test_reset_rejects_ambiguous_raw_destinations(tmp_path: Path) -> None:
    """
    Two portable groups cannot restore different originals to the same filename.
    """
    _portable_run(tmp_path)
    other = tmp_path / 'control/other'
    (other / '.fits_experiment').mkdir(parents=True)
    (other / 'sample.nd2').write_bytes(b'other acquisition')
    with pytest.raises(ValueError, match='ambiguous'):
        plan_reset(tmp_path)
    assert (other / 'sample.nd2').read_bytes() == b'other acquisition'


def test_reset_handles_interrupted_grouping_and_acquisition_as_run(tmp_path: Path) -> None:
    """
    Portable groups without state restore safely, and a run-root raw stays inside the run.
    """
    acquisition = tmp_path / 'sample'
    (acquisition / '.fits_experiment').mkdir(parents=True)
    (acquisition / 'sample.nd2').write_bytes(b'raw')
    reset_run(acquisition)
    assert (acquisition / 'sample.nd2').read_bytes() == b'raw'
    assert not (acquisition / '.fits_experiment').exists()
    (acquisition / '.fits_experiment').mkdir()
    reset_run(tmp_path)
    assert (tmp_path / 'sample.nd2').read_bytes() == b'raw'
    assert not acquisition.exists()


def test_reset_legacy_state_keeps_ungrouped_original(tmp_path: Path) -> None:
    """
    Legacy state is removed without moving an already ungrouped raw acquisition.
    """
    original = tmp_path / 'sample.nd2'
    original.write_bytes(b'raw')
    series = tmp_path / 'sample_s1'
    series.mkdir()
    (series / 'experiment_state.json').write_text(json.dumps({'artifacts': {'raw_image': '../sample.nd2'}}))
    (series / cst.FITS_ARRAY_NAME).write_bytes(b'old pixels')
    reset_run(tmp_path)
    assert list(tmp_path.iterdir()) == [original]
    assert original.read_bytes() == b'raw'


def test_reset_respects_active_run_lock(tmp_path: Path) -> None:
    """
    A pipeline holding the shared write guard prevents any reset writes.
    """
    original = _portable_run(tmp_path)
    with run_write_guard(tmp_path):
        with pytest.raises(RuntimeError, match='already active'):
            reset_run(tmp_path)
    assert original.exists()
    assert (tmp_path / cst.MASTER_QUANTI_NAME).exists()


def test_reset_reports_partial_failure_and_preserves_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    An I/O failure after removal starts retains raw bytes and reports incomplete work.
    """
    original = _portable_run(tmp_path)
    before = original.read_bytes()
    unlink = Path.unlink

    def fail_removal(path: Path, missing_ok: bool = False) -> None:
        """
        Simulate an output that cannot be removed after the raw was restored.
        """
        if path.name == cst.FITS_MASK_TRACK:
            raise PermissionError(f'File is in use: {path}')
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, 'unlink', fail_removal)
    with pytest.raises(RuntimeError, match='Some FITS files may already have been removed'):
        reset_run(tmp_path)
    assert (tmp_path / 'control/sample.nd2').read_bytes() == before
    assert not original.exists()
