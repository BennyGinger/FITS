import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from typing import cast

from fits.gui.viewer.registration import RegistrationTunerWindow
from fits.settings.loader import load_settings, run_settings_path
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.tuned import load_tuning

_APP = None


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
        time_settings=RegisterTimeSettings(backend='scikit', fit_channel=0),
        channel_settings=RegisterChannelSettings(backend='scikit', reference_channel=0))
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
    assert window.channel_combo.currentIndex() == 1
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


def test_complete_without_preview_saves_both_tabs_and_closes(window, source):
    """Complete an unpreviewed session without calculating any transforms."""
    accepted = []
    window.settings_applied.connect(lambda mode, settings: accepted.append(mode))
    assert window.complete_button.isEnabled()
    window.complete_button.click()
    assert not window.isVisible()
    assert accepted == ['time', 'channel']
    for mode in ('time', 'channel'):
        saved = load_tuning(source, mode)
        assert saved is not None and saved.register is None


def test_gui_settings_take_priority_over_previous_experiment_tuning(window, source):
    """Opening from GUI values preserves backend, method, reference and fit channel."""
    assert window._session is not None
    window._session.save_settings(RegisterTimeSettings(context='complex_drift', fit_channel=0))
    provided = RegisterTimeSettings(context='rotational_drift', backend='scikit',
                                    method='translation', reference_strategy='first', fit_channel=1)
    tuner = RegistrationTunerWindow(source.parent, time_settings=provided)
    try:
        current = tuner.current_settings()
        assert isinstance(current, RegisterTimeSettings)
        assert current.fit_channel == tuner.channel_combo.itemText(1)
        assert tuner.channel_combo.currentIndex() == 1
        assert tuner.panels['time'].backend.currentText() == 'scikit'
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


def test_display_channel_selects_time_fitting_channel_and_invalidates_preview(window):
    """Update the active fitting/reference channel after explicit display selection."""
    window.tabs.setCurrentIndex(0)
    window._run_preview()
    wait_for_preview(window)
    assert window.save_button.isEnabled()
    window.channel_combo.setCurrentIndex(1)
    assert window.panels['time'].channel.currentIndex() == 1
    assert window.current_settings().fit_channel == window.channel_combo.currentText()
    assert window.save_button.isEnabled()
    window._run_preview()
    wait_for_preview(window)
    assert window.save_button.isEnabled(), window.status_label.text()
    window.tabs.setCurrentIndex(1)
    window.channel_combo.setCurrentIndex(0)
    assert window.panels['channel'].channel.currentIndex() == 0
    assert window.panels['time'].channel.currentIndex() == 1
    window.tabs.setCurrentIndex(0)
    assert window.channel_combo.currentIndex() == 1


@pytest.mark.parametrize('mode,strategy', [('time', 'previous'), ('time', 'first'), ('channel', None)])
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


def test_standalone_saves_general_settings(source):
    """Verify standalone saves general settings."""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    window = RegistrationTunerWindow(source.parent)
    window.show()
    window._open_source(source)
    window.panels['time'].backend.setCurrentText('scikit')
    window.panels['time'].strategy.setCurrentText('first')
    window._run_preview()
    wait_for_preview(window)
    window._save_settings()
    saved = load_settings(run_settings_path(source.parent))
    assert saved['register_time']['params']['backend'] == 'scikit'
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
    window._run_preview()
    for _ in range(100):
        QTest.qWait(10)
        if entered:
            break
    assert entered
    assert not window.complete_button.isEnabled()
    window.close()
    wait_for_preview(window)
    assert not window.isVisible()
    assert window._session is None


@pytest.mark.parametrize('stale_channel', [False, True])
def test_complete_saves_matching_tabs_and_closes(window, source, stale_channel):
    """Verify complete saves matching tabs and closes."""
    accepted = []
    window.settings_applied.connect(lambda mode, settings: accepted.append(mode))
    window._run_preview()
    wait_for_preview(window)
    window.tabs.setCurrentIndex(0)
    window._run_preview()
    wait_for_preview(window)

    window.save_button.click()
    assert window.isVisible()
    assert load_tuning(source, 'time') is not None
    assert load_tuning(source, 'channel') is None
    accepted.clear()
    if stale_channel:
        window.panels['channel'].reference_frame.setValue(2)

    window.complete_button.click()
    assert not window.isVisible()
    assert window._session is None
    assert accepted == ['time', 'channel']
    saved_channel = load_tuning(source, 'channel')
    assert saved_channel is not None
    assert (saved_channel.register is None) == stale_channel
    if stale_channel:
        assert isinstance(saved_channel.settings, RegisterChannelSettings)
        assert saved_channel.settings.reference_frame == 1


def test_complete_save_failure_keeps_viewer_open(window, monkeypatch):
    """Verify complete save failure keeps viewer open."""
    window._run_preview()
    wait_for_preview(window)

    def fail_save(preview):
        """Simulate an unsuccessful settings write."""
        raise OSError('Cannot write transforms')

    monkeypatch.setattr(window._session, 'save_preview', fail_save)
    window.complete_button.click()
    assert window.isVisible()
    assert 'Cannot write transforms' in window.status_label.text()


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
    tuner.panels['channel'].backend.setCurrentText('scikit')
    tuner._run_preview()
    wait_for_preview(tuner)
    tuner._save_settings()
    assert main.adapter.field_value(StepName.REGISTER_CHANNEL, 'backend') == 'scikit'
    editor = main._editors[StepName.REGISTER_CHANNEL]
    assert editor._advanced_group.isChecked()
    assert editor.widgets['backend'].value() == 'scikit'
    assert editor.widgets['method'].value() == 'translation'
    assert load_tuning(source, 'channel') is not None
    main._open_registration_tuner('time')
    assert main._registration_tuner is tuner
    assert tuner.mode() == 'time'
    context_widget = editor.widgets['context']
    from fits.gui.settings.field_widgets import ChoiceWidget
    assert isinstance(context_widget, ChoiceWidget)
    context_widget.setCurrentText('channel_shift_complex')
    assert main.adapter.field_value(StepName.REGISTER_CHANNEL, 'backend') == 'cv2'
    assert main.adapter.field_value(StepName.REGISTER_CHANNEL, 'method') == 'affine'
    assert editor.widgets['backend'].value() == 'cv2'
    assert editor.widgets['method'].value() == 'affine'
    tuner.panels['time'].backend.setCurrentText('scikit')
    tuner.panels['time'].method.setCurrentText('translation')
    tuner._run_preview()
    wait_for_preview(tuner)
    tuner._save_settings()
    assert main._editors[StepName.REGISTER_TIME].advanced_settings_visible
    assert main._editors[StepName.REGISTER_CHANNEL].advanced_settings_visible
    tuner.close()
    main.close()


@pytest.mark.parametrize('mode,context,backend,method', [
    ('time', 'linear_drift', 'pystackreg', 'translation'),
    ('time', 'rotational_drift', 'pystackreg', 'rigid_body'),
    ('time', 'complex_drift', 'pystackreg', 'affine'),
    ('channel', 'channel_shift', 'cv2', 'translation'),
    ('channel', 'channel_shift_dual_cam', 'cv2', 'rigid_body'),
    ('channel', 'channel_shift_complex', 'cv2', 'affine'),
])
def test_presets_fill_actual_choices_and_manual_edits_select_custom(window, mode, context, backend, method):
    """Keep preset display, explicit edits and CLI-compatible payloads consistent."""
    window.tabs.setCurrentIndex(0 if mode == 'time' else 1)
    panel = window.panels[mode]
    panel.context.setCurrentText(context)
    assert panel.backend.currentText() == backend
    assert panel.method.currentText() == method
    assert panel.manual_status.text() == 'Set by context'
    assert panel.resolved.text().startswith(f'{backend} / {method} / ')
    panel.backend.setCurrentText('cv2' if backend == 'pystackreg' else 'pystackreg')
    assert panel.context.currentText() == 'Custom'
    assert panel.manual_status.text() == 'Manual settings'
    assert panel.method.currentText() == method
    assert panel.settings().context == context
    panel.context.setCurrentText(context)
    assert panel.backend.currentText() == backend
    alternative = 'affine' if method != 'affine' else 'translation'
    panel.method.setCurrentText(alternative)
    expected = ('complex_drift' if mode == 'time' else 'channel_shift_complex') if alternative == 'affine' else ('linear_drift' if mode == 'time' else 'channel_shift')
    assert panel.context.currentText() == expected
    assert panel.settings().context == expected
    assert panel.settings().backend == backend
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
    panel.load(RegisterTimeSettings(context='rotational_drift', backend='cv2', fit_channel=0),
               session.channel_labels, session.frame_count)
    assert panel.context.currentText() == 'Custom'
    assert panel.backend.currentText() == 'cv2'
    assert panel.method.currentText() == 'rigid_body'
    assert panel.settings().context == 'rotational_drift'
    panel.load(RegisterTimeSettings(context='linear_drift', backend='pystackreg', method='translation', fit_channel=0),
               session.channel_labels, session.frame_count)
    assert panel.context.currentText() == 'linear_drift'
    assert panel.manual_status.text() == 'Set by context'
