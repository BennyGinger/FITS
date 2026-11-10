import numpy as np
import json
from contextlib import closing
from pathlib import Path
import pytest
import tifffile
from scope_io import ScopeIO
from stackalign import RegisterModel

from fits.environment.constant import StepName
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.register_channel import register_channel
from fits.tasks.registration.register_time import register_time
from fits.tasks.registration.tuned import Mode, load_tuning, tuning_path
from fits.tasks.registration.tuning import RegistrationTuningSession
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.definitions.inputs import configured_profile
from fits.workflows.experiments import ExperimentState
from fits.workflows.checks.models import ArtifactRecord
from fits.workflows.checks.settings import settings_problem


@pytest.fixture
def source(tmp_path):
    """Write a small multichannel Z stack with known time and channel shifts."""
    (tmp_path / '.fits_experiment').mkdir(exist_ok=True)
    path = tmp_path / 'fits_array.tif'
    first = np.zeros((32, 32), dtype=np.uint16)
    first[8:13, 9:15] = 1000
    array = np.stack([np.stack([np.stack([np.roll(first, t + c, axis=0) * (z + 1)
                                        for z in range(2)]) for c in range(2)]) for t in range(4)])
    tifffile.imwrite(path, array.swapaxes(1, 2), imagej=True, metadata={'axes': 'TZCYX'})
    return path


def time_settings() -> RegisterTimeSettings:
    """
    Use translation fitting against adjacent original frames.
    """
    return RegisterTimeSettings(algorithm='scikit', reference_strategy='previous', fit_channel=0)


def channel_settings() -> RegisterChannelSettings:
    """
    Use one reference frame and the first reference channel.
    """
    return RegisterChannelSettings(algorithm='scikit', reference_channel=0, reference_frame=1)


def materialize_preview(session, preview):
    """Assemble only a small test fixture explicitly through the lazy plane API."""
    output = np.empty(session.shape, dtype=np.uint16)
    for frame, channel, z in session._planes.keys():
        output[session._plane_selection(frame, channel, z)] = session.preview_frame(preview, frame, channel, z)
    return output


def test_legacy_tuning_keeps_its_transforms(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Load old backend-named metadata and reuse its unchanged fitting signature.
    """
    with closing(RegistrationTuningSession(source)) as session:
        preview = session.run_preview("time", time_settings())
        path = session.save_preview(preview)
        with np.load(path, allow_pickle=False) as stored:
            metadata = json.loads(str(stored["metadata"].item()))
            transform = stored["transform"].copy()
        assert metadata["algorithm"] == "scikit"
        assert "backend" not in metadata
        metadata["backend"] = metadata.pop("algorithm")
        metadata["settings"]["backend"] = metadata["settings"].pop("algorithm")
        np.savez_compressed(path, metadata=np.asarray(json.dumps(metadata)), transform=transform)

    restored = load_tuning(source, "time")
    assert restored is not None
    assert restored.settings.algorithm == "scikit"

    def unexpected_fit(*args: object, **kwargs: object) -> None:
        """
        Fail if a field rename causes existing transforms to be fitted again.
        """
        pytest.fail("The algorithm rename invalidated saved fitting transforms.")

    monkeypatch.setattr("fits.tasks.registration.tuning.fit_planes", unexpected_fit)
    with closing(RegistrationTuningSession(source)) as session:
        reused = session.run_preview("time", time_settings())
        assert reused.result.signature == restored.signature


def test_preview_is_virtual_cached_and_does_not_modify_source(source, monkeypatch):
    """Fit without eager input/output stacks and apply only requested planes."""
    original = source.read_bytes()
    monkeypatch.setattr(ScopeIO, 'get_array', lambda *a, **kw: pytest.fail('Eager input stack load'))
    session = RegistrationTuningSession(source)
    assert not session._planes._cache
    preview = session.run_preview('time', time_settings())
    assert not preview.planes
    plane = session.preview_frame(preview, 2, 1, 0)
    assert plane.shape == (32, 32)
    assert plane.dtype == np.uint16
    assert len(preview.planes) == 1
    assert session.preview_frame(preview, 2, 1, 0) is plane
    assert source.read_bytes() == original
    monkeypatch.setattr('fits.tasks.registration.tuning.fit_planes',
                        lambda *a, **kw: pytest.fail('Repeated fitting for unchanged controls'))
    assert session.run_preview('time', time_settings()) is preview
    session.close()


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_crop_limits_fit_and_preserves_full_image_preview(source, monkeypatch, mode):
    """Fit only ROI pixels while retaining full-image output and persistent crop scope."""
    from fits.tasks.registration import tuning
    real_fit = tuning.fit_planes
    fitted_shapes = []

    def capture_fit(array, **kwargs):
        """Record the actual fitting shape before running the algorithm."""
        fitted_shapes.append(array.shape)
        return real_fit(array, **kwargs)

    monkeypatch.setattr(tuning, 'fit_planes', capture_fit)
    settings = time_settings() if mode == 'time' else channel_settings()
    crop = (4, 3, 26, 25)
    session = RegistrationTuningSession(source)
    preview = session.run_preview(mode, settings, crop=crop)
    assert fitted_shapes == [(4 if mode == 'time' else 2, 22, 22)]
    assert session.preview_frame(preview, 3, 1, 1).shape == (32, 32)
    assert session.cached_preview(mode, settings) is None
    assert session.cached_preview(mode, settings, crop=crop) is preview
    assert session.cached_preview(mode, settings, crop=(5, 3, 27, 25)) is None
    session.save_preview(preview)
    saved = load_tuning(source, mode)
    assert saved is not None and saved.crop == crop
    expected = materialize_preview(session, preview)
    session.close()
    fitted_shapes.clear()
    restored = RegistrationTuningSession(source)
    np.testing.assert_array_equal(materialize_preview(restored, restored.run_preview(mode, settings, crop=crop)), expected)
    assert not fitted_shapes
    restored.close()


@pytest.mark.parametrize('algorithm,method', [('scikit', 'translation'), ('cv2', 'translation'),
                                         ('cv2', 'rigid_body'), ('cv2', 'affine'),
                                         ('pystackreg', 'translation'), ('pystackreg', 'rigid_body'),
                                         ('pystackreg', 'affine')])
def test_crop_origin_conversion_matches_local_warp(algorithm, method):
    """Verify translation, rotation and affine crop origins using each real algorithm."""
    from scipy.ndimage import gaussian_filter
    from fits.tasks.registration.tuned import full_image_model
    crop = (30, 20, 110, 100)
    full = np.zeros((128, 150), dtype=np.float32)
    full[35:85, 45:95] = gaussian_filter(np.random.default_rng(6).random((50, 50)), 1)
    local = full[20:100, 30:110]
    matrix = np.eye(3)
    matrix[:2, 2] = (2, -1)
    if method != 'translation':
        matrix[:2, :2] = [[0, -1], [1, 0]]
        matrix[:2, 2] = (75, 1)
    if method == 'affine':
        # Binary-exact coefficients avoid OpenCV's 1/32-pixel interpolation
        # table rounding differently after an otherwise equivalent origin shift.
        matrix[:2, :2] = [[1, 0.125], [0.0625, 1]]
        matrix[:2, 2] = (2, -1)
    local_register = full_image_model(matrix[None], algorithm=algorithm, mode='time', method=method,
                                      reference_channel=None, crop=None)
    lifted = full_image_model(matrix[None], algorithm=algorithm, mode='time', method=method,
                              reference_channel=None, crop=crop)
    expected = local_register.apply_plane(local)
    actual = lifted.apply_plane(full)[20:100, 30:110]
    np.testing.assert_allclose(actual[10:-10, 10:-10], expected[10:-10, 10:-10], atol=1e-4)


def test_lazy_preview_cache_is_bounded_and_does_not_apply_unvisited_planes(source, monkeypatch):
    """Keep only visited planes and evict old entries from the bounded cache."""
    session = RegistrationTuningSession(source)
    preview = session.run_preview('time', time_settings())
    calls = []
    assert preview.result.register is not None
    real_apply = preview.result.register.apply_plane

    def apply(array, **kwargs):
        """Record every actual plane transformation."""
        calls.append(kwargs)
        return real_apply(array, **kwargs)

    monkeypatch.setattr(preview.result.register, 'apply_plane', apply)
    assert not calls
    for frame, channel, z in session._planes.keys():
        session.preview_frame(preview, frame, channel, z)
    assert len(calls) == 16 and len(preview.planes) == 8
    session.preview_frame(preview, 3, 1, 1)
    assert len(calls) == 16
    session.preview_frame(preview, 0, 0, 0)
    assert len(calls) == 17
    session.close()
    assert not session._previews
    assert not (source.parent / '.fits' / 'viewer_cache' / 'registration').exists()


@pytest.mark.parametrize('mode', ['time', 'channel'])
@pytest.mark.parametrize('cropped', [False, True])
def test_settings_only_save_is_fitted_by_pipeline(source: Path, tmp_path: Path, mode: Mode, cropped: bool) -> None:
    """
    Fit the configured settings using the tuner's optional saved crop.
    """
    settings = time_settings() if mode == 'time' else channel_settings()
    crop = (4, 3, 26, 25) if cropped else None
    session = RegistrationTuningSession(source)
    session.save_settings(settings, crop=crop)
    saved = load_tuning(source, mode)
    assert saved is not None and saved.register is None
    expected = materialize_preview(session, session.run_preview(mode, settings, crop=crop))
    session.close()
    raw = tmp_path / 'raw.nd2'
    raw.write_bytes(b'raw')
    state = ExperimentState.init(tmp_path, raw).with_complete_step(
        step_name=StepName.CONVERT, artifact_kind='image_raw', artifact_path=source)
    if mode == 'time':
        register_time(time_settings(), state,
                      configured_profile(REGISTRY[StepName.REGISTER_TIME].profile, {"convert": {"enabled": True}}))
    else:
        register_channel(channel_settings(), state,
                         configured_profile(REGISTRY[StepName.REGISTER_CHANNEL].profile, {"convert": {"enabled": True}}))
    output_name = 'fits_array_reg.tif' if mode == 'time' else 'fits_array_reg_channel.tif'
    np.testing.assert_array_equal(ScopeIO.from_path(source.with_name(output_name)).get_array().array, expected)


@pytest.mark.parametrize('mode', ['time', 'channel'])
@pytest.mark.parametrize('cropped', [False, True])
def test_pipeline_settings_override_older_tuner_cache(source: Path,
                                                     tmp_path: Path,
                                                     mode: Mode,
                                                     cropped: bool,
                                                     ) -> None:
    """
    Honour later channel choices and record the actual configured settings in outputs.
    """
    crop = (4, 3, 26, 25) if cropped else None
    with closing(RegistrationTuningSession(source)) as session:
        if mode == 'time':
            old = time_settings()
            current = old.model_copy(update={'fit_channel': 1, 'reference_strategy': 'first'})
        else:
            old = channel_settings()
            current = old.model_copy(update={'reference_channel': 1, 'reference_frame': 2})
        session.save_preview(session.run_preview(mode, old, crop=crop))
        expected = materialize_preview(session, session.run_preview(mode, current, crop=crop))
    raw = tmp_path / 'raw.nd2'
    raw.write_bytes(b'raw')
    state = ExperimentState.init(tmp_path, raw).with_complete_step(
        step_name=StepName.CONVERT, artifact_kind='image_raw', artifact_path=source)
    step = StepName.REGISTER_TIME if mode == 'time' else StepName.REGISTER_CHANNEL
    profile = configured_profile(REGISTRY[step].profile, {'convert': {'enabled': True}})
    if isinstance(current, RegisterTimeSettings):
        result = register_time(current, state, profile)[0]
    else:
        result = register_channel(current, state, profile)[0]
    output = result.artifact(profile.output_artifact)
    assert output is not None
    reader = ScopeIO.from_path(output)
    np.testing.assert_array_equal(reader.get_array().array, expected)
    params = reader.metadata.custom_metadata['steps'][step]['params']
    assert params['fit_channel' if mode == 'time' else 'reference_channel'] == 1
    record = ArtifactRecord(output, step, reader.metadata)
    assert settings_problem(record, {step: {'enabled': True, 'params': current.model_dump()}}) == ''


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_saved_models_reload_without_fitting(source, monkeypatch, mode):
    """Restore accepted transforms and lazily reproduce the same image planes."""
    settings = time_settings() if mode == 'time' else channel_settings()
    session = RegistrationTuningSession(source)
    preview = session.run_preview(mode, settings)
    expected = materialize_preview(session, preview)
    session.save_preview(preview)
    session.close()
    monkeypatch.setattr('fits.tasks.registration.tuning.fit_planes',
                        lambda *a, **kw: pytest.fail('Saved transform was fitted again'))
    restored = RegistrationTuningSession(source)
    np.testing.assert_array_equal(materialize_preview(restored, restored.run_preview(mode, settings)), expected)
    restored.close()


@pytest.mark.parametrize('cropped', [False, True])
def test_pipeline_reuses_both_modes_with_matching_settings(source: Path,
                                                          tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch,
                                                          cropped: bool,
                                                          ) -> None:
    """
    Reuse both cached transforms when their settings still match the run configuration.
    """
    session = RegistrationTuningSession(source)
    crop = (4, 3, 26, 25) if cropped else None
    time_preview = session.run_preview('time', time_settings(), crop=crop)
    channel_preview = session.run_preview('channel', channel_settings(), upstream=time_settings(),
                                          crop=crop, upstream_crop=crop)
    expected = materialize_preview(session, channel_preview)
    session.save_preview(time_preview)
    session.save_preview(channel_preview)
    session.close()
    monkeypatch.setattr('stackalign.backends.execution.EXECUTOR_MODE', 'thread')
    monkeypatch.setattr(RegisterModel, 'fit_time', lambda *a, **kw: pytest.fail('Time fitted again'))
    monkeypatch.setattr(RegisterModel, 'fit_channel', lambda *a, **kw: pytest.fail('Channels fitted again'))
    monkeypatch.setattr('fits.tasks.registration.tuned.fit_planes',
                        lambda *a, **kw: pytest.fail('Accepted crop was fitted again'))
    raw = tmp_path / 'raw.nd2'
    raw.write_bytes(b'raw')
    state = ExperimentState.init(tmp_path, raw).with_complete_step(
        step_name=StepName.CONVERT, artifact_kind='image_raw', artifact_path=source)
    state = register_time(time_settings(), state,
                          configured_profile(REGISTRY[StepName.REGISTER_TIME].profile, {"convert": {"enabled": True}}))[0]
    from dataclasses import replace
    profile = replace(REGISTRY[StepName.REGISTER_CHANNEL].profile, input_artifact='image_time_registered', input_alternatives=())
    state = register_channel(channel_settings(), state, profile)[0]
    assert state.last_step == StepName.REGISTER_CHANNEL
    output = state.artifact('image_channel_registered')
    assert output is not None
    np.testing.assert_array_equal(ScopeIO.from_path(output).get_array().array, expected)


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_saved_crop_refits_only_its_pixels_when_pipeline_input_changes(source, monkeypatch, mode):
    """Ignore changes outside the fitting crop and preserve ROI scope when refitting."""
    from fits.tasks.registration import tuned
    session = RegistrationTuningSession(source)
    settings = time_settings() if mode == 'time' else channel_settings()
    crop = (4, 3, 26, 25)
    session.save_preview(session.run_preview(mode, settings, crop=crop))
    session.close()
    saved = load_tuning(source, mode)
    assert saved is not None
    reader = ScopeIO.from_path(source)
    array = reader.get_array().array.copy()
    array[..., 0, 0] = 777
    def reuse():
        """Check reuse against the current pixels and resolved channel positions."""
        return tuned.reusable_model(saved, array=array, axes=reader.axes,
                                    labels=tuple(reader.channel_labels), settings=settings,
                                    fit_channel=0, reference_channel=0 if mode == 'channel' else None)

    assert reuse() is saved.register
    array[..., 10, 10] = 777
    shapes = []
    real_fit = tuned.fit_planes

    def fit_roi(fitting, **kwargs):
        """Record cropped input dimensions during pipeline refitting."""
        shapes.append(fitting.shape)
        return real_fit(fitting, **kwargs)

    monkeypatch.setattr(tuned, 'fit_planes', fit_roi)
    updated = reuse()
    assert updated is not None and updated is not saved.register
    assert shapes == [(4 if mode == 'time' else 2, 22, 22)]


def test_changed_fitting_pixels_recompute_and_corrupt_cache_is_ignored(source, monkeypatch):
    """Recompute changed fitting inputs and reject unreadable accepted models."""
    session = RegistrationTuningSession(source)
    preview = session.run_preview('time', time_settings())
    session.save_preview(preview)
    session.close()
    array = ScopeIO.from_path(source).get_array().array
    array[1, :, 0, 3, 4] = 777
    tifffile.imwrite(source, array, imagej=True, metadata={'axes': 'TZCYX'})
    from fits.tasks.registration import tuning
    original = tuning.fit_planes
    calls = []
    def fit(*args, **kwargs):
        """Record fits while retaining the real numerical implementation."""
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
    """Keep cancelled fits out of the ready preview and accepted model stores."""
    session = RegistrationTuningSession(source)
    with pytest.raises(InterruptedError):
        session.run_preview('time', time_settings(), cancelled=lambda: True)
    assert session.cached_preview('time', time_settings()) is None
    assert not tuning_path(source, 'time').exists()
    session.close()


def test_source_changes_block_lazy_preview_and_saving(source):
    """Prevent new source pixels from being combined with older fitted transforms."""
    session = RegistrationTuningSession(source)
    preview = session.run_preview('time', time_settings())
    session.preview_frame(preview)
    source.write_bytes(source.read_bytes() + b'\0')
    with pytest.raises(ValueError, match='source image changed'):
        session.preview_frame(preview)
    with pytest.raises(ValueError, match='source changed'):
        session.save_preview(preview)
    session.close()


def test_excluded_channel_is_not_fitted_or_changed(source, monkeypatch):
    """Leave excluded channels unchanged without running a fitting kernel."""
    from fits.tasks.registration import tuning
    from stackalign.planes import plane_functions
    original = plane_functions
    def functions(algorithm, method):
        """Replace the fitting kernel with a failure to detect unexpected work."""
        fit, apply = original(algorithm, method)
        def unexpected(*args, **kwargs):
            """Fail if an excluded channel is fitted."""
            pytest.fail('Excluded channel was fitted')
        return unexpected, apply
    monkeypatch.setattr('stackalign.planes.plane_functions', functions)
    session = RegistrationTuningSession(source)
    labels = session.channel_labels
    settings = RegisterChannelSettings(algorithm='scikit', reference_channel=labels[0],
                                       exclude_channel=[labels[1]])
    preview = session.run_preview('channel', settings)
    np.testing.assert_array_equal(materialize_preview(session, preview), ScopeIO.from_path(source).get_array().array)
    session.close()
