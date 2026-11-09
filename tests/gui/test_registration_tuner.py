import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea, QWidget
from typing import Any, cast

from fits.gui.viewer.registration import RegistrationTunerWindow
from fits.settings.loader import load_settings, run_settings_path
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.tuned import load_tuning

_APP = None


@pytest.fixture(autouse=True)
def discard_unsaved_tuning(monkeypatch):
    """Allow unrelated tests to clean up windows without a modal prompt."""
    monkeypatch.setattr('fits.gui.viewer.registration.window.confirm_discard_tuner_changes',
                        lambda parent, tabs: True)


def drag_crop(window, start, end):
    """Draw through the real viewport so inactive tabs cannot capture the gesture."""
    canvas = window.image_viewer.canvas
    viewport = cast(QWidget, canvas.viewport())
    first = cast(QPoint, canvas.mapFromScene(window.image_viewer.view_box.mapViewToScene(QPointF(*start))))
    last = cast(QPoint, canvas.mapFromScene(window.image_viewer.view_box.mapViewToScene(QPointF(*end))))
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(last), QPointF(viewport.mapToGlobal(last)),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, move)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, last)
    QApplication.processEvents()


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_registration_crop_is_opt_in_per_tab_and_disabling_restores_full_view(window, mode):
    """Draw only when enabled and invalidate crop-based previews when disabled."""
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    panel = window.crops[mode]
    assert not panel.enabled.isChecked()
    assert panel.crop_button is None
    assert panel.bounds is None
    drag_crop(window, (4, 4), (25, 25))
    assert panel.bounds is None
    window.image_viewer.reset_view()
    panel.enabled.setChecked(True)
    drag_crop(window, (4, 4), (25, 25))
    assert panel.bounds is not None
    bounds = panel.bounds
    assert window.crops['channel' if mode == 'time' else 'time'].bounds is None
    assert window._crop() == bounds
    panel.preview_button.setChecked(True)
    zoom = window.image_viewer.view_box.viewRange()
    window._run_preview()
    wait_for_preview(window)
    assert window.save_button.isEnabled(), window.status_label.text()
    window.frame_slider.setValue(2)
    assert window.image_viewer.image_item.image.shape == (32, 32)
    panel.enabled.setChecked(False)
    assert panel.bounds == bounds
    assert window._crop() is None
    assert not panel.rectangle.isVisible()
    assert not panel.preview_button.isChecked()
    assert window.image_viewer.view_box.viewRange() != zoom
    assert window.save_button.isEnabled()
    panel.enabled.setChecked(True)
    assert window.save_button.isEnabled()


@pytest.fixture
def source(tmp_path):
    """Write a small microscopy fixture with known channel and time shifts."""
    path = tmp_path / 'fits_array.tif'
    image = np.zeros((32, 32), dtype=np.uint16)
    image[8:14, 9:13] = 1000
    array = np.stack([np.stack([np.roll(image, t + c, axis=0) for c in range(2)])
                      for t in range(3)])
    tifffile.imwrite(path, array, imagej=True, metadata={'axes': 'TCYX'})
    return path


def wait_for_preview(window):
    """Wait for the preview worker to finish while processing Qt events."""
    for _ in range(1000):
        QTest.qWait(10)
        if window._thread is None:
            return
    pytest.fail('Registration preview worker did not finish')


@pytest.fixture
def window(source):
    """Open a viewer fixture and close it after the test."""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    window = RegistrationTunerWindow(
        source.parent, mode='channel',
        time_settings=RegisterTimeSettings(algorithm='scikit', fit_channel=0),
        channel_settings=RegisterChannelSettings(algorithm='scikit', reference_channel=0))
    window.show()
    window._open_source(source)
    yield window
    window.close()
    wait_for_preview(window)
    window.close()


def test_shared_tabs_background_preview_save_and_stale_controls(window, source):
    """Verify shared tabs background preview save and stale controls."""
    assert window.mode() == 'channel'
    session = window._session
    assert session is not None
    assert window.channel_combo.currentIndex() == 0
    assert window.save_button.isEnabled()
    accepted = []
    window.settings_applied.connect(lambda mode, settings: accepted.append((mode, settings)))
    window.run_button.click()
    assert window._thread is not None
    wait_for_preview(window)
    assert window.save_button.isEnabled(), window.status_label.text()
    assert window._composite_item.isVisible()
    window.save_button.click()
    assert accepted[0][0] == 'channel'
    assert load_tuning(source, 'channel') is not None
    window.panels['channel'].reference_frame.setValue(2)
    assert window.save_button.isEnabled()
    window.tabs.setCurrentIndex(0)
    assert window._session is session
    assert window.mode() == 'time'
    window.run_button.click()
    wait_for_preview(window)
    assert window.save_button.isEnabled(), window.status_label.text()


def test_channel_preview_is_independent_of_time_settings(window):
    """Channel fitting uses the source image and has no time-preview checkbox."""
    assert not hasattr(window, 'use_time')
    window._run_preview()
    wait_for_preview(window)
    assert window._session is not None
    preview = window._session.cached_preview('channel', window.current_settings())
    assert preview is not None
    assert preview.upstream is None
    window.panels['time'].strategy.setCurrentText('first')
    assert window.save_button.isEnabled()


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_save_current_without_preview_persists_only_selected_tab(window, source, mode):
    """Accept unpreviewed settings and a crop without fitting either tab."""
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    crop = window.crops[mode]
    crop.set_bounds((4, 3, 26, 25))
    crop.enabled.setChecked(True)
    accepted = []
    window.settings_applied.connect(lambda mode, settings: accepted.append(mode))
    assert window.save_button.isEnabled()
    window.save_button.click()
    saved = load_tuning(source, mode)
    assert saved is not None
    assert saved.register is None
    assert saved.crop == crop.bounds
    assert saved.settings == window.current_settings()
    assert accepted == [mode]
    assert load_tuning(source, 'channel' if mode == 'time' else 'time') is None
    assert window.isVisible()


def test_close_unchanged_session_does_not_save(window, source, monkeypatch):
    """Close a freshly opened tuner without saving either tab or showing a warning."""
    accepted = []
    warnings = []
    monkeypatch.setattr('fits.gui.viewer.registration.window.confirm_discard_tuner_changes',
                        lambda parent, tabs: warnings.append(tabs) or False)
    window.settings_applied.connect(lambda mode, settings: accepted.append(mode))
    assert window.close_button.isEnabled()
    assert window.close_button.text() == 'Close window'
    window.close_button.click()
    assert not window.isVisible()
    assert accepted == []
    assert warnings == []
    for mode in ('time', 'channel'):
        assert load_tuning(source, mode) is None


def test_gui_settings_take_priority_over_previous_experiment_tuning(window, source):
    """Opening from GUI values preserves algorithm, method, reference and fit channel."""
    assert window._session is not None
    window._session.save_settings(RegisterTimeSettings(context='complex_drift', fit_channel=0))
    provided = RegisterTimeSettings(context='rotational_drift', algorithm='scikit',
                                    method='translation', reference_strategy='first', fit_channel=1)
    tuner = RegistrationTunerWindow(source.parent, time_settings=provided)
    try:
        current = tuner.current_settings()
        assert isinstance(current, RegisterTimeSettings)
        assert current.fit_channel == tuner.channel_combo.itemText(1)
        assert tuner.channel_combo.currentIndex() == 1
        assert tuner.panels['time'].algorithm.currentText() == 'scikit'
        assert tuner.panels['time'].method.currentText() == 'translation'
        assert tuner.panels['time'].strategy.currentText() == 'first'
        assert tuner.panels['time'].context.currentText() == 'Custom'
    finally:
        tuner.close()


@pytest.mark.parametrize('width', [1200, 1700])
def test_registration_tabs_share_settings_and_resolved_panel_geometry(window, width):
    """Changing registration tabs keeps the settings and pinned summary aligned."""
    window.resize(width, 950)
    geometries = []
    for index in (0, 1):
        window.tabs.setCurrentIndex(index)
        QTest.qWait(10)
        panel = window.panels[window.mode()]
        scroll = panel.findChild(QScrollArea)
        assert scroll is not None
        geometries.append((scroll.geometry(), panel.resolved_group.geometry()))
    assert geometries[0] == geometries[1]


def test_display_browsing_preserves_fitting_channel_and_preview(window: RegistrationTunerWindow) -> None:
    """
    Browse with C without changing fitting settings; fitting selection updates display.
    """
    window.tabs.setCurrentIndex(0)
    window._run_preview()
    wait_for_preview(window)
    session = window._session
    assert session is not None
    settings = window.current_settings()
    preview = session.cached_preview('time', settings, crop=window._crop())
    assert preview is not None
    QTest.keyClick(window, Qt.Key.Key_C)
    assert window.channel_combo.currentIndex() == 1
    assert window.current_settings() == settings
    assert session.cached_preview('time', window.current_settings(), crop=window._crop()) is preview
    window.panels['time'].channel.setCurrentText(window.channel_combo.itemText(1))
    window.channel_combo.setCurrentIndex(0)
    selected_settings = window.current_settings()
    assert isinstance(selected_settings, RegisterTimeSettings)
    assert selected_settings.fit_channel == window.channel_combo.itemText(1)
    window.panels['time'].channel.setCurrentText(window.channel_combo.itemText(0))
    assert window.channel_combo.currentIndex() == 0
    window.panels['time'].channel.setCurrentText(window.channel_combo.itemText(1))
    assert window.channel_combo.currentIndex() == 1
    window.tabs.setCurrentIndex(1)
    window.channel_combo.setCurrentIndex(1)
    assert window.panels['channel'].channel.currentText() == window.channel_combo.itemText(0)
    window.tabs.setCurrentIndex(0)
    assert window.channel_combo.currentIndex() == 1


@pytest.mark.parametrize('mode,strategy', [('time', 'previous'), ('time', 'first')])
def test_composite_overlays_current_original_with_registered_channel_colour(window, monkeypatch, mode, strategy):
    """Show raw-versus-registered displacement and swap the raw colour for grayscale LUTs."""
    import pyqtgraph as pg
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    if strategy is not None:
        window.panels['time'].strategy.setCurrentText(strategy)
    window._run_preview()
    wait_for_preview(window)
    window.frame_slider.setValue(2)
    window.comparison.setCurrentIndex(2)
    gradient = window.image_viewer.histogram.item.gradient
    gradient.setColorMap(pg.ColorMap([0, 1], [(0, 0, 0, 255), (0, 255, 0, 255)]))
    session = window._session
    assert session is not None
    requested = []
    real_frame = session.preview_frame

    def record_frame(preview, frame_index=0, channel=0, z_index=0):
        """Verify that rendering requests the current registered plane only."""
        requested.append((frame_index, channel, z_index))
        return real_frame(preview, frame_index, channel, z_index)

    monkeypatch.setattr(session, 'preview_frame', record_frame)
    window._display_selection()
    channel = window.channel_combo.currentText()
    assert requested == [(2, channel, 0)]
    composite = window._composite_item.image
    assert composite.shape == (32, 32, 3)
    raw_only_row = 15 if mode == 'time' else 16
    registered_only_row = 8 if mode == 'time' else 10
    np.testing.assert_allclose(composite[raw_only_row, 10], [1, 1, 1], atol=1e-4)
    np.testing.assert_allclose(composite[registered_only_row, 10], [0, 1, 0], atol=1e-4)
    window.grayscale_lut_button.setChecked(True)
    QTest.qWait(20)
    composite = window._composite_item.image
    np.testing.assert_allclose(composite[raw_only_row, 10], [1, 0, 1], atol=1e-4)
    np.testing.assert_allclose(composite[registered_only_row, 10], [1, 1, 1], atol=1e-4)
    assert window._composite_item.isVisible()
    window.frame_slider.setValue(0)
    assert window._composite_item.isVisible()


def test_channel_reference_selection_updates_display_in_one_direction(window):
    """Reference choices select the display, while browsing preserves the fitted reference."""
    panel = window.panels['channel']
    panel.channel.setCurrentText(window.channel_combo.itemText(1))
    assert window.channel_combo.currentIndex() == 1
    window._run_preview()
    wait_for_preview(window)
    settings = window.current_settings()
    preview = window._session.cached_preview('channel', settings)
    window.channel_combo.setCurrentIndex(0)
    assert window.current_settings() == settings
    assert window._session.cached_preview('channel', settings) is preview
    window.tabs.setCurrentIndex(0)
    assert [window.comparison.itemText(i) for i in range(window.comparison.count())] == [
        'Registered image', 'Original image', 'Composite overlay']
    window.tabs.setCurrentIndex(1)
    assert window.channel_combo.currentIndex() == 1
    assert [window.comparison.itemText(i) for i in range(window.comparison.count())] == [
        'Original alignment', 'Registered alignment']


def test_channel_alignment_overlays_two_channels_with_stable_reference_and_contrast(window: RegistrationTunerWindow,
                                                                                  monkeypatch: pytest.MonkeyPatch,
                                                                                  ) -> None:
    """
    Render an unchanged reference with original/registered versions of the same other channel.
    """
    session = window._session
    assert session is not None
    reference, other = session.channel_labels
    window.frame_slider.setValue(2)
    window.comparison.setCurrentIndex(0)
    original = np.asarray(window._composite_item.image).copy()
    assert not window.comparison.model().flags(window.comparison.model().index(1, 0)) & Qt.ItemFlag.ItemIsEnabled
    window._run_preview()
    wait_for_preview(window)
    requested = []
    real_frame = session.preview_frame
    def record_frame(preview, frame_index=0, channel=0, z_index=0):
        requested.append((frame_index, channel, z_index))
        return real_frame(preview, frame_index, channel, z_index)
    monkeypatch.setattr(session, 'preview_frame', record_frame)
    window._display_selection()
    registered = np.asarray(window._composite_item.image).copy()
    assert requested == [(2, other, 0)]
    np.testing.assert_allclose(original[..., 0], registered[..., 0])
    np.testing.assert_allclose(original[..., 2], registered[..., 2])
    assert not np.array_equal(original[..., 1], registered[..., 1])
    assert np.count_nonzero(registered[..., 0] != registered[..., 1]) < np.count_nonzero(original[..., 0] != original[..., 1])
    assert reference in window.comparison.toolTip() and other in window.comparison.toolTip()
    assert not window.image_viewer.histogram.isEnabled()
    assert window.image_viewer.pixel_readout.isEnabled()
    assert not window.grayscale_lut_button.isEnabled()
    window.comparison.setCurrentIndex(0)
    np.testing.assert_allclose(np.asarray(window._composite_item.image), original)
    window.comparison.setCurrentIndex(1)
    monkeypatch.setattr(session, 'preview_frame', lambda *args: real_frame(*args) * 0.5)
    window._display_selection()
    np.testing.assert_allclose(np.asarray(window._composite_item.image)[..., 1], registered[..., 1] * 0.5)
    np.testing.assert_allclose(np.asarray(window._composite_item.image)[..., 0], registered[..., 0])
    window.panels['channel'].reference_frame.setValue(2)
    np.testing.assert_allclose(np.asarray(window._composite_item.image), original)
    assert window.comparison.currentIndex() == 0
    assert not window.comparison.model().flags(window.comparison.model().index(1, 0)) & Qt.ItemFlag.ItemIsEnabled


@pytest.mark.parametrize('reference_index', [None, 1])
def test_unset_reference_defaults_to_first_channel_and_saved_reference_is_preserved(window, source, reference_index):
    """Accept the visible default on save, preserving explicit references when present."""
    panel = window.panels['channel']
    panel.load(RegisterChannelSettings(reference_channel=reference_index),
               window._session.channel_labels, window._session.frame_count)
    expected = window._session.channel_labels[reference_index or 0]
    assert panel.channel.currentText() == expected
    assert window.channel_combo.currentText() == expected
    window.save_button.click()
    assert load_tuning(source, 'channel').settings.reference_channel == expected


@pytest.mark.parametrize('channels', [1, 3])
def test_channel_alignment_cycles_included_comparisons_and_handles_no_pair(window, tmp_path, channels, monkeypatch):
    """Cycle comparisons around a fixed reference and retain manual access to excluded channels."""
    folder = tmp_path / 'additional'
    folder.mkdir()
    path = folder / 'fits_array.tif'
    pixels = np.zeros((3, channels, 32, 32), dtype=np.uint16)
    pixels[..., 8:14, 9:13] = 1000
    tifffile.imwrite(path, pixels, imagej=True, metadata={'axes': 'TCYX'})
    tuner = RegistrationTunerWindow(folder, mode='channel')
    tuner.show()
    tuner.activateWindow()
    monkeypatch.setattr(tuner, 'isActiveWindow', lambda: True)
    tuner.image_viewer.setFocus()
    try:
        labels = tuner._session.channel_labels
        assert tuner.current_settings().reference_channel == labels[0]
        if channels == 3:
            assert f'comparison: {labels[1]}' in tuner.comparison.toolTip()
            QTest.keyClick(tuner.image_viewer, Qt.Key.Key_C)
            assert tuner.channel_combo.currentIndex() == 2
            assert f'comparison: {labels[2]}' in tuner.comparison.toolTip()
            QTest.keyClick(tuner.image_viewer, Qt.Key.Key_C)
            assert tuner.channel_combo.currentIndex() == 1
            assert f'comparison: {labels[1]}' in tuner.comparison.toolTip()
            tuner.channel_combo.setCurrentIndex(2)
            assert tuner.current_settings().reference_channel == labels[0]
            assert f'comparison: {labels[2]}' in tuner.comparison.toolTip()
            tuner.panels['channel'].excluded.item(1).setCheckState(Qt.CheckState.Checked)
            QTest.keyClick(tuner.image_viewer, Qt.Key.Key_C)
            assert tuner.channel_combo.currentIndex() == 2
            assert f'comparison: {labels[2]}' in tuner.comparison.toolTip()
            tuner.channel_combo.setCurrentIndex(1)
            assert 'excluded' in tuner.comparison.toolTip()
            assert not tuner._composite_item.isVisible()
            QTest.keyClick(tuner.image_viewer, Qt.Key.Key_C)
            assert tuner.channel_combo.currentIndex() == 2
            tuner.panels['channel'].excluded.item(2).setCheckState(Qt.CheckState.Checked)
            QTest.keyClick(tuner.image_viewer, Qt.Key.Key_C)
            assert tuner.channel_combo.currentIndex() == 2
            tuner.channel_combo.setCurrentIndex(0)
        QTest.keyClick(tuner.image_viewer, Qt.Key.Key_C)
        assert tuner.channel_combo.currentIndex() == 0
        assert not tuner._composite_item.isVisible()
        assert tuner.image_viewer.image_item.isVisible()
        assert 'No other included channel' in tuner.comparison.toolTip()
        np.testing.assert_array_equal(tuner.image_viewer.image_item.image, pixels[0, 0])
    finally:
        tuner.close()


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_composite_hover_reads_unblended_planes_without_loading_more_images(window: RegistrationTunerWindow,
                                                                           monkeypatch: pytest.MonkeyPatch,
                                                                           mode: str,
                                                                           ) -> None:
    """
    Report each composite source intensity using only the planes already rendered.
    """
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    window.frame_slider.setValue(2)
    window._run_preview()
    wait_for_preview(window)
    window.comparison.setCurrentIndex(2 if mode == 'time' else 1)
    session = window._session
    assert session is not None
    preview = session.cached_preview(window.mode(), window.current_settings(), crop=window._crop())
    assert preview is not None
    if mode == 'time':
        channel = window.channel_combo.currentText()
        names = (f'Original {channel}', f'Registered {channel}')
        planes = (session.display_frame(2, channel, 0), session.preview_frame(preview, 2, channel, 0))
    else:
        reference, channel = session.channel_labels
        names = (reference, channel)
        planes = (session.display_frame(2, reference, 0), session.preview_frame(preview, 2, channel, 0))

    def forbid_loading(*args: object, **kwargs: object) -> None:
        """
        Fail if hovering requests another raw or registered image plane.
        """
        pytest.fail('Hovering must only sample existing planes')

    monkeypatch.setattr(session, 'display_frame', forbid_loading)
    monkeypatch.setattr(session, 'preview_frame', forbid_loading)
    readout = window.image_viewer.pixel_readout
    monkeypatch.setattr(readout._viewport, 'underMouse', lambda: True)
    point = window.image_viewer.image_item.mapToScene(cast(Any, QPointF(10.2, 10.2)))
    readout._mouse_moved((cast(QPointF, point),))
    assert [tag.toolTip() for tag in readout.tags] == list(names)
    assert [value.toolTip() for value in readout.values] == [
        f'{name}: {plane[10, 10].item()}' for name, plane in zip(names, planes)]
    assert readout.isEnabled()


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_preview_choices_require_matching_registration(window: RegistrationTunerWindow, mode: str) -> None:
    """
    Disable processed choices and V until the current tab has a matching preview.
    """
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    original = 1 if mode == 'time' else 0
    combo = window.comparison
    model = combo.model()
    assert combo.currentIndex() == original
    for index in range(combo.count()):
        assert bool(model.flags(model.index(index, 0)) & Qt.ItemFlag.ItemIsEnabled) == (index == original)
    QTest.keyClick(window, Qt.Key.Key_V)
    assert combo.currentIndex() == original
    window._run_preview()
    wait_for_preview(window)
    assert all(model.flags(model.index(index, 0)) & Qt.ItemFlag.ItemIsEnabled for index in range(combo.count()))
    panel = window.panels[window.mode()]
    if mode == 'time':
        panel.strategy.setCurrentText('first' if panel.strategy.currentText() != 'first' else 'previous')
    else:
        panel.reference_frame.setValue(2)
    assert combo.currentIndex() == original
    for index in range(combo.count()):
        assert bool(model.flags(model.index(index, 0)) & Qt.ItemFlag.ItemIsEnabled) == (index == original)


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_v_compares_registration_without_moving_selection_and_x_does_not(window, monkeypatch, mode):
    """Use V for before/after in both modes, preserving selection, contrast and settings."""
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    window.frame_slider.setValue(2)
    window._run_preview()
    wait_for_preview(window)
    window.image_viewer.set_display_levels((0, 1500))
    window.activateWindow()
    window.image_viewer.setFocus()
    monkeypatch.setattr(window, 'isActiveWindow', lambda: True)
    settings = window.current_settings()
    selection = (window.frame_slider.value(), window.channel_combo.currentIndex(), window.z_slider.value())
    processed_index = 0 if mode == 'time' else 1
    original_index = 1 - processed_index
    assert window.comparison.currentIndex() == processed_index
    processed = (window.image_viewer.image_item.image if mode == 'time' else window._composite_item.image).copy()
    QTest.keyClick(window.image_viewer, Qt.Key.Key_V)
    assert window.comparison.currentIndex() == original_index
    original = window.image_viewer.image_item.image if mode == 'time' else window._composite_item.image
    assert not np.array_equal(original, processed)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_X)
    assert window.comparison.currentIndex() == original_index
    QTest.keyClick(window.image_viewer, Qt.Key.Key_V)
    assert window.comparison.currentIndex() == processed_index
    np.testing.assert_allclose(window.image_viewer.image_item.image if mode == 'time' else window._composite_item.image,
                               processed)
    assert window.current_settings() == settings
    assert selection == (window.frame_slider.value(), window.channel_combo.currentIndex(), window.z_slider.value())
    assert window.image_viewer.display_levels == (0, 1500)
    if mode == 'time':
        QTest.keyClick(window.image_viewer, Qt.Key.Key_C)
        assert window.channel_combo.currentIndex() == 1
        QTest.keyClick(window.image_viewer, Qt.Key.Key_C)
        assert window.channel_combo.currentIndex() == 0


def test_standalone_saves_general_settings(source):
    """Verify standalone saves general settings."""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    window = RegistrationTunerWindow(source.parent)
    window.show()
    window._open_source(source)
    window.panels['time'].algorithm.setCurrentText('scikit')
    window.panels['time'].strategy.setCurrentText('first')
    window._run_preview()
    wait_for_preview(window)
    window._save_settings()
    saved = load_settings(run_settings_path(source.parent))
    assert saved['register_time']['params']['algorithm'] == 'scikit'
    assert saved['register_time']['params']['reference_strategy'] == 'first'
    assert load_tuning(source, 'time') is not None
    window.close()


def test_close_during_preview_cancels_before_closing(window, monkeypatch):
    """Verify close during preview cancels before closing."""
    import time
    entered = []
    def slow_preview(*args, cancelled, **kwargs):
        """Keep fitting active until cancellation is requested."""
        entered.append(True)
        while not cancelled():
            time.sleep(0.005)
        raise InterruptedError()
    monkeypatch.setattr(window._session, 'run_preview', slow_preview)
    window.panels['channel'].reference_frame.setValue(2)
    window._run_preview()
    for _ in range(100):
        QTest.qWait(10)
        if entered:
            break
    assert entered
    assert window.close_button.isEnabled()
    monkeypatch.setattr('fits.gui.viewer.registration.window.confirm_discard_tuner_changes',
                        lambda parent, tabs: False)
    window.close_button.click()
    assert window.isVisible()
    assert window._thread is not None
    assert not window._thread.isInterruptionRequested()
    monkeypatch.setattr('fits.gui.viewer.registration.window.confirm_discard_tuner_changes',
                        lambda parent, tabs: True)
    window.close_button.click()
    wait_for_preview(window)
    assert not window.isVisible()
    assert window._session is None


@pytest.mark.parametrize('use_title_bar', [False, True])
def test_close_warns_for_both_tabs_and_discard_does_not_save(window, source, monkeypatch, use_title_bar):
    """Protect inactive-tab changes and let users return to editing or discard."""
    accepted = []
    window.settings_applied.connect(lambda mode, settings: accepted.append(mode))
    window.panels['channel'].reference_frame.setValue(2)
    window.tabs.setCurrentIndex(0)
    window.panels['time'].strategy.setCurrentText('first')
    warnings = []
    def keep_editing(parent, tabs):
        warnings.append(tabs)
        return False
    monkeypatch.setattr('fits.gui.viewer.registration.window.confirm_discard_tuner_changes', keep_editing)
    close = window.close if use_title_bar else window.close_button.click
    close()
    assert window.isVisible()
    assert warnings == [['Time registration', 'Channel registration']]
    assert accepted == []
    window.save_button.click()
    assert window.isVisible()
    assert load_tuning(source, 'time') is not None
    assert load_tuning(source, 'channel') is None
    accepted.clear()
    assert window._unsaved_tabs() == ['Channel registration']
    monkeypatch.setattr('fits.gui.viewer.registration.window.confirm_discard_tuner_changes',
                        lambda parent, tabs: True)
    close()
    assert not window.isVisible()
    assert window._session is None
    assert accepted == []
    assert load_tuning(source, 'channel') is None


def test_save_failure_keeps_unsaved_changes(window, monkeypatch):
    """A failed save keeps the viewer open and still warns before closing."""
    window.panels['channel'].reference_frame.setValue(2)
    window._run_preview()
    wait_for_preview(window)

    def fail_save(preview):
        """Simulate an unsuccessful settings write."""
        raise OSError('Cannot write transforms')

    monkeypatch.setattr(window._session, 'save_preview', fail_save)
    window.save_button.click()
    assert window.isVisible()
    assert 'Cannot write transforms' in window.status_label.text()
    assert window._unsaved_tabs() == ['Channel registration']


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_unsaved_crop_and_reverted_settings(window, mode):
    """Track effective crop changes and clear warnings after reverting or saving."""
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    panel = window.panels[mode]
    panel.overwrite.setChecked(True)
    assert window._unsaved_tabs()
    panel.overwrite.setChecked(False)
    assert window._unsaved_tabs() == []
    crop = window.crops[mode]
    crop.set_bounds((4, 3, 26, 25))
    crop.enabled.setChecked(True)
    assert window._unsaved_tabs() == [f'{mode.title()} registration']
    window.save_button.click()
    assert window._unsaved_tabs() == []
    crop.enabled.setChecked(False)
    assert window._unsaved_tabs() == [f'{mode.title()} registration']
    crop.enabled.setChecked(True)
    assert window._unsaved_tabs() == []


def test_close_compares_used_tab_with_live_main_settings(window):
    """Resolve equivalent preset/index values and detect later main-GUI changes."""
    saved = window._defaults['channel'].model_copy(deep=True)
    window._settings_provider = lambda mode: saved
    window._run_preview()
    wait_for_preview(window)
    assert window._unsaved_tabs() == []
    saved.reference_frame = 1
    assert window._unsaved_tabs() == ['Channel registration']


def test_invalid_unsaved_settings_still_warn(window):
    """Clearing a required reference channel must not bypass the close warning."""
    window.panels['channel'].channel.setCurrentIndex(0)
    assert window._unsaved_tabs() == ['Channel registration']


@pytest.mark.parametrize('discard', [False, True])
def test_shared_unsaved_dialog_defaults_to_keep_editing(window, discard):
    """Exercise the actual dialog choices with a safe default and Escape action."""
    from fits.gui.viewer.common.tuner_actions import confirm_discard_tuner_changes
    def choose():
        message = QApplication.activeModalWidget()
        assert isinstance(message, QMessageBox)
        assert 'Time registration' in message.text()
        assert message.defaultButton().text() == 'Keep editing'
        assert message.escapeButton().text() == 'Keep editing'
        button = next(button for button in message.buttons()
                      if button.text() == ('Close without saving' if discard else 'Keep editing'))
        button.click()
    QTimer.singleShot(0, choose)
    assert confirm_discard_tuner_changes(window, ['Time registration']) is discard


def test_main_gui_opens_requested_tab_and_accepts_general_settings(source):
    """Verify main gui opens requested tab and accepts general settings."""
    from fits.environment.constant import StepName
    from fits.gui.main_window.window import FitsMainWindow
    global _APP
    _APP = QApplication.instance() or QApplication([])
    main = FitsMainWindow()
    main.run_dir_edit.setText(str(source.parent))
    main._open_registration_tuner('channel')
    tuner = main._registration_tuner
    assert tuner is not None
    assert tuner.mode() == 'channel'
    tuner._open_source(source)
    tuner.panels['channel'].channel.setCurrentText(tuner.channel_combo.itemText(0))
    tuner.panels['channel'].algorithm.setCurrentText('scikit')
    tuner._run_preview()
    wait_for_preview(tuner)
    tuner._save_settings()
    assert main.adapter.field_value(StepName.REGISTER_CHANNEL, 'algorithm') == 'scikit'
    editor = main._editors[StepName.REGISTER_CHANNEL]
    assert editor._advanced_group.isChecked()
    assert editor.widgets['algorithm'].value() == 'scikit'
    assert editor.widgets['method'].value() == 'translation'
    assert load_tuning(source, 'channel') is not None
    assert tuner._unsaved_tabs() == []
    main._open_registration_tuner('time')
    assert main._registration_tuner is tuner
    assert tuner.mode() == 'time'
    context_widget = editor.widgets['context']
    from fits.gui.settings.field_widgets import ChoiceWidget
    assert isinstance(context_widget, ChoiceWidget)
    context_widget.setCurrentText('channel_shift_complex')
    assert main.adapter.field_value(StepName.REGISTER_CHANNEL, 'algorithm') == 'cv2'
    assert main.adapter.field_value(StepName.REGISTER_CHANNEL, 'method') == 'affine'
    assert editor.widgets['algorithm'].value() == 'cv2'
    assert editor.widgets['method'].value() == 'affine'
    assert tuner._unsaved_tabs() == ['Channel registration']
    tuner.panels['time'].algorithm.setCurrentText('scikit')
    tuner.panels['time'].method.setCurrentText('translation')
    tuner._run_preview()
    wait_for_preview(tuner)
    tuner._save_settings()
    assert main._editors[StepName.REGISTER_TIME].advanced_settings_visible
    assert main._editors[StepName.REGISTER_CHANNEL].advanced_settings_visible
    tuner.close()
    main.close()


@pytest.mark.parametrize('mode,context,algorithm,method', [
    ('time', 'linear_drift', 'pystackreg', 'translation'),
    ('time', 'rotational_drift', 'pystackreg', 'rigid_body'),
    ('time', 'complex_drift', 'pystackreg', 'affine'),
    ('channel', 'channel_shift', 'cv2', 'translation'),
    ('channel', 'channel_shift_dual_cam', 'cv2', 'rigid_body'),
    ('channel', 'channel_shift_complex', 'cv2', 'affine'),
])
def test_presets_fill_actual_choices_and_manual_edits_select_custom(window, mode, context, algorithm, method):
    """Keep preset display, explicit edits and CLI-compatible payloads consistent."""
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    panel = window.panels[mode]
    panel.context.setCurrentText(context)
    assert panel.algorithm.currentText() == algorithm
    assert panel.method.currentText() == method
    assert panel.manual_status.text() == 'Set by context'
    assert panel.resolved.text().startswith(f'{algorithm} / {method} / ')
    panel.algorithm.setCurrentText('cv2' if algorithm == 'pystackreg' else 'pystackreg')
    assert panel.context.currentText() == 'Custom'
    assert panel.manual_status.text() == 'Manual settings'
    assert panel.method.currentText() == method
    assert panel.settings().context == context
    panel.context.setCurrentText(context)
    assert panel.algorithm.currentText() == algorithm
    alternative = 'affine' if method != 'affine' else 'translation'
    panel.method.setCurrentText(alternative)
    expected = ('complex_drift' if mode == 'time' else 'channel_shift_complex') if alternative == 'affine' else ('linear_drift' if mode == 'time' else 'channel_shift')
    assert panel.context.currentText() == expected
    assert panel.settings().context == expected
    assert panel.settings().algorithm == algorithm
    panel.method.setCurrentText(method)
    assert panel.context.currentText() == context


@pytest.mark.parametrize('mode', ['time', 'channel'])
def test_resolved_summary_is_last_and_tracks_reference_and_active_crop(window, mode):
    """Show effective reference and fitting scope in the final titled subpanel."""
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    panel = window.panels[mode]
    outer = panel.sections_layout
    assert [outer.itemAt(index).widget() for index in range(2)] == [
        panel.registration_group, panel.crop_group]
    layout = panel.layout()
    assert layout is not None
    assert layout.itemAt(layout.count() - 1).widget() is panel.resolved_group
    scroll = panel.findChild(QScrollArea)
    assert scroll is not None
    assert not scroll.isAncestorOf(panel.resolved_group)
    QTest.qWait(10)
    position = panel.resolved_group.geometry()
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    QApplication.processEvents()
    assert panel.resolved_group.geometry() == position
    assert panel.resolved_group.accessibleName() == 'Resolved registration'
    assert panel.context.parentWidget() is panel.registration_group
    assert panel.manual_group.parentWidget() is panel.registration_group
    assert panel.resolved.text().endswith('/ full image')
    if mode == 'time':
        panel.strategy.setCurrentText('first')
        assert ' / first / ' in panel.resolved.text()
        panel.strategy.setCurrentText('previous')
        assert ' / previous / ' in panel.resolved.text()
    else:
        panel.reference_frame.setValue(2)
        assert f'reference {panel.channel.currentText()}, frame 2' in panel.resolved.text()
    crop = window.crops[mode]
    assert crop.parentWidget() is panel.crop_group
    assert panel.crop_group.accessibleName() == 'Fitting crop'
    assert 'full image' in panel.crop_description.text()
    crop.set_bounds((4, 3, 26, 25))
    assert panel.resolved.text().endswith('/ full image')
    crop.enabled.setChecked(True)
    assert panel.resolved.text().endswith('/ from crop')
    crop.enabled.setChecked(False)
    assert panel.resolved.text().endswith('/ full image')


def test_loading_overrides_shows_custom_with_resolved_unspecified_fields(window):
    """Resolve partial CLI overrides and infer Custom only for a differing effective plan."""
    session = window._session
    assert session is not None
    panel = window.panels['time']
    panel.load(RegisterTimeSettings(context='rotational_drift', algorithm='cv2', fit_channel=0),
               session.channel_labels, session.frame_count)
    assert panel.context.currentText() == 'Custom'
    assert panel.algorithm.currentText() == 'cv2'
    assert panel.method.currentText() == 'rigid_body'
    assert panel.settings().context == 'rotational_drift'
    panel.load(RegisterTimeSettings(context='linear_drift', algorithm='pystackreg', method='translation', fit_channel=0),
               session.channel_labels, session.frame_count)
    assert panel.context.currentText() == 'linear_drift'
    assert panel.manual_status.text() == 'Set by context'
