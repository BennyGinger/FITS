import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget
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
    assert not window.save_button.isEnabled()
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
    assert not window.save_button.isEnabled()
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
    assert not window.save_button.isEnabled()
    window.tabs.setCurrentIndex(0)
    assert window._session is session
    assert window.mode() == 'time'
    window.run_button.click()
    wait_for_preview(window)
    assert window.save_button.isEnabled(), window.status_label.text()


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
    assert accepted == (['time'] if stale_channel else ['time', 'channel'])
    assert (load_tuning(source, 'channel') is None) == stale_channel


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
    assert load_tuning(source, 'channel') is not None
    main._open_registration_tuner('time')
    assert main._registration_tuner is tuner
    assert tuner.mode() == 'time'
    tuner.close()
    main.close()
