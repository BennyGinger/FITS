import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fits.gui.viewer.registration import RegistrationTunerWindow
from fits.settings.loader import load_settings, run_settings_path
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.tuned import load_tuning

_APP = None


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'fits_array.tif'
    image = np.zeros((32, 32), dtype=np.uint16)
    image[8:14, 9:13] = 1000
    array = np.stack([np.stack([np.roll(image, t + c, axis=0) for c in range(2)])
                      for t in range(3)])
    tifffile.imwrite(path, array, imagej=True, metadata={'axes': 'TCYX'})
    return path


def wait_for_preview(window):
    for _ in range(1000):
        QTest.qWait(10)
        if window._thread is None:
            return
    pytest.fail('Registration preview worker did not finish')


@pytest.fixture
def window(source):
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


def test_complete_during_preview_cancels_before_closing(window, monkeypatch):
    import time
    entered = []
    def slow_preview(*args, cancelled, **kwargs):
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
    window.complete_button.click()
    wait_for_preview(window)
    assert not window.isVisible()
    assert window._session is None


def test_main_gui_opens_requested_tab_and_accepts_general_settings(source):
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
