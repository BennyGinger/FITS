from pathlib import Path

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO
from stackalign import RegisterModel

from fits.environment.constant import StepName
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.register_channel import register_channel
from fits.tasks.registration.register_time import register_time
from fits.tasks.registration.tuned import load_tuning, tuning_path
from fits.tasks.registration.tuning import RegistrationTuningSession
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'fits_array.tif'
    first = np.zeros((32, 32), dtype=np.uint16)
    first[8:13, 9:15] = 1000
    array = np.stack([np.stack([np.stack([np.roll(first, t + c, axis=0) * (z + 1)
                                        for z in range(2)]) for c in range(2)]) for t in range(4)])
    tifffile.imwrite(path, array.swapaxes(1, 2), imagej=True, metadata={'axes': 'TZCYX'})
    return path


def time_settings():
    return RegisterTimeSettings(backend='scikit', reference_strategy='previous', fit_channel=0)


def channel_settings():
    return RegisterChannelSettings(backend='scikit', reference_channel=0, reference_frame=1)


def test_preview_is_virtual_cached_and_does_not_modify_source(source, monkeypatch):
    original = source.read_bytes()
    monkeypatch.setattr(FitsIO, 'get_array', lambda *a, **kw: pytest.fail('Eager input stack load'))
    session = RegistrationTuningSession(source)
    assert not session._planes._cache
    preview = session.run_preview('time', time_settings())
    assert isinstance(preview.array, np.memmap)
    assert preview.array.shape == session.shape
    assert preview.array.dtype == np.uint16
    assert source.read_bytes() == original
    monkeypatch.setattr('fits.tasks.registration.tuning.fit_planes',
                        lambda *a, **kw: pytest.fail('Repeated fitting for unchanged controls'))
    assert session.run_preview('time', time_settings()) is preview
    cache = Path(session._temporary.name)
    session.close()
    assert not cache.exists()


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_saved_models_reload_without_fitting(source, monkeypatch, mode):
    settings = time_settings() if mode == 'time' else channel_settings()
    session = RegistrationTuningSession(source)
    preview = session.run_preview(mode, settings)
    expected = preview.array.copy()
    session.save_preview(preview)
    session.close()
    monkeypatch.setattr('fits.tasks.registration.tuning.fit_planes',
                        lambda *a, **kw: pytest.fail('Saved transform was fitted again'))
    restored = RegistrationTuningSession(source)
    np.testing.assert_array_equal(restored.run_preview(mode, settings).array, expected)
    restored.close()


def test_pipeline_reuses_both_modes_in_order_even_after_general_settings_change(source, tmp_path, monkeypatch):
    session = RegistrationTuningSession(source)
    time_preview = session.run_preview('time', time_settings())
    channel_preview = session.run_preview('channel', channel_settings(), upstream=time_settings())
    expected = channel_preview.array.copy()
    session.save_preview(time_preview)
    session.save_preview(channel_preview)
    session.close()
    monkeypatch.setattr('stackalign.backends.execution.EXECUTOR_MODE', 'thread')
    monkeypatch.setattr(RegisterModel, 'fit_time', lambda *a, **kw: pytest.fail('Time fitted again'))
    monkeypatch.setattr(RegisterModel, 'fit_channel', lambda *a, **kw: pytest.fail('Channels fitted again'))
    raw = tmp_path / 'raw.nd2'
    raw.write_bytes(b'raw')
    state = ExperimentState.init(tmp_path, raw).with_complete_step(
        step_name=StepName.CONVERT, artifact_kind='image', artifact_path=source)
    state = register_time(RegisterTimeSettings(context='complex_drift'), state,
                          REGISTRY[StepName.REGISTER_TIME].profile)[0]
    state = register_channel(RegisterChannelSettings(reference_channel=1), state,
                             REGISTRY[StepName.REGISTER_CHANNEL].profile)[0]
    assert state.last_step == StepName.REGISTER_CHANNEL
    np.testing.assert_array_equal(FitsIO.from_path(source).get_array().array, expected)


def test_changed_fitting_pixels_recompute_and_corrupt_cache_is_ignored(source, monkeypatch):
    session = RegistrationTuningSession(source)
    preview = session.run_preview('time', time_settings())
    session.save_preview(preview)
    session.close()
    array = FitsIO.from_path(source).get_array().array
    array[1, :, 0, 3, 4] = 777
    tifffile.imwrite(source, array, imagej=True, metadata={'axes': 'TZCYX'})
    from fits.tasks.registration import tuning
    original = tuning.fit_planes
    calls = []
    def fit(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(tuning, 'fit_planes', fit)
    session = RegistrationTuningSession(source)
    session.run_preview('time', time_settings())
    assert calls == [True]
    session.close()
    tuning_path(source, 'time').write_bytes(b'not a valid npz')
    assert load_tuning(source, 'time') is None


def test_cancelled_preview_cannot_be_saved(source):
    session = RegistrationTuningSession(source)
    with pytest.raises(InterruptedError):
        session.run_preview('time', time_settings(), cancelled=lambda: True)
    assert session.cached_preview('time', time_settings()) is None
    assert not tuning_path(source, 'time').exists()
    session.close()


def test_excluded_channel_is_not_fitted_or_changed(source, monkeypatch):
    from fits.tasks.registration import tuning
    from stackalign.planes import plane_functions
    original = plane_functions
    def functions(backend, method):
        fit, apply = original(backend, method)
        def unexpected(*args, **kwargs):
            pytest.fail('Excluded channel was fitted')
        return unexpected, apply
    monkeypatch.setattr('stackalign.planes.plane_functions', functions)
    session = RegistrationTuningSession(source)
    labels = session.channel_labels
    settings = RegisterChannelSettings(backend='scikit', reference_channel=labels[0],
                                       exclude_channel=[labels[1]])
    preview = session.run_preview('channel', settings)
    np.testing.assert_array_equal(preview.array, FitsIO.from_path(source).get_array().array)
    session.close()
