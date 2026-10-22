"""Background tuner navigation, measurement, worker lifecycle and settings transfer."""

import os
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import tifffile
from bg_sub import bg_sub
from typing import cast
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidget, QWidget

from fits.environment.constant import StepName
from fits.gui.main_window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.gui.viewer.background import BackgroundTunerWindow
from fits.gui.viewer.common.information_dialog import ViewerInformationDialog
from fits.settings.loader import load_settings, run_settings_path
from fits.settings.models import BGSubSettings

_APP = None


@pytest.fixture(autouse=True)
def application():
    """Keep one application alive across isolated offscreen viewer tests."""
    global _APP
    _APP = QApplication.instance() or QApplication([])


@pytest.fixture
def source(tmp_path):
    """Write distinguishable frames, channels and Z planes without full-stack processing."""
    path = tmp_path / "fits_array.tif"
    image = np.random.default_rng(4).integers(100, 400, (32, 32), dtype=np.uint16)
    image[8:16, 10:18] += 1000
    array = np.stack([np.stack([np.stack([image + t * 10 + c * 20 + z * 5
                                       for c in range(2)]) for z in range(2)]) for t in range(4)])
    tifffile.imwrite(path, array, imagej=True, metadata={"axes": "TZCYX"})
    return path


def wait_for_preview(window):
    """Process Qt events until all explicitly requested planes have finished."""
    for _ in range(1000):
        QTest.qWait(10)
        if window._thread is None:
            return
    pytest.fail("Background preview did not finish")


@pytest.fixture
def window(source):
    """Open a tuner on the first image with small pipeline-compatible parameters."""
    viewer = BackgroundTunerWindow(source.parent, settings=BGSubSettings(size=3, bg_workers=2))
    viewer.show()
    viewer.activateWindow()
    QTest.qWait(10)
    yield viewer
    viewer._preview_enabled = False
    wait_for_preview(viewer)
    viewer.close()


def test_requested_planes_only_comparison_shortcut_and_measurement(window):
    """Measure raw values, preserve display levels and process only visited selections."""
    session = window._session
    assert session is not None
    assert window._source_path is not None
    assert not session._previews
    assert window.settings_panel.settings().bg_workers == 2
    box = window.settings_panel.measurement
    assert not box.enabled.isChecked()
    box.enabled.setChecked(True)
    box.set_bounds((4, 3, 26, 25))
    window.image_viewer.set_display_levels((0, 2000))
    window.run_button.click()
    wait_for_preview(window)
    assert len(session._previews) == 1
    channel = window.channel_combo.currentText()
    raw = session.display_frame(0, channel, 0)
    expected = bg_sub(raw, size=3, execution="sequential")
    np.testing.assert_array_equal(window.image_viewer.image_item.image, np.maximum(expected, 0))
    assert expected.dtype == np.float32 and np.any(expected < 0)
    cached = session.cached_preview(window.settings_panel.settings(), 0, channel, 0)
    assert cached is not None and np.any(cached < 0)
    text = window.settings_panel.means.text()
    assert f"Original mean: {np.mean(raw[3:25, 4:26]):.6g}" in text
    assert f"Processed mean: {np.mean(expected[3:25, 4:26], dtype=np.float64):.6g}" in text
    window.image_viewer.setFocus()
    QTest.keyClick(window.image_viewer, Qt.Key.Key_V)
    assert window.comparison.currentIndex() == 0
    np.testing.assert_array_equal(window.image_viewer.image_item.image, raw)
    assert window.image_viewer.display_levels == (0, 2000)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_V)
    assert window.comparison.currentIndex() == 1
    assert len(session._previews) == 1
    window.frame_slider.setValue(2)
    wait_for_preview(window)
    assert len(session._previews) == 2
    assert session.cached_preview(window.settings_panel.settings(), 1, channel, 0) is None
    window.settings_panel.threshold.setValue(0.2)
    assert not window._preview_enabled
    assert window._thread is None
    np.testing.assert_array_equal(window.image_viewer.image_item.image, session.display_frame(2, channel, 0))
    assert "Processed mean: run preview" in window.settings_panel.means.text()


def test_navigation_during_work_processes_latest_selection_without_propagation(window, monkeypatch):
    """Skip intermediate navigation requests and never display the previous plane's output."""
    session = window._session
    assert session is not None
    real_compute = session.compute_plane
    entered, release = Event(), Event()
    calls = []

    def compute(image, settings, frame, channel, z):
        """Hold the first request while the user selects another plane."""
        calls.append((frame, channel, z))
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return real_compute(image, settings, frame, channel, z)

    monkeypatch.setattr(session, "compute_plane", compute)
    window._run_preview()
    try:
        for _ in range(100):
            QTest.qWait(10)
            if entered.is_set():
                break
        assert entered.is_set()
        window.frame_slider.setValue(1)
        window.frame_slider.setValue(3)
        window.channel_combo.setCurrentIndex(1)
        window.z_slider.setValue(1)
    finally:
        release.set()
    wait_for_preview(window)
    assert len(calls) == 2
    assert calls[-1] == (3, window.channel_combo.currentText(), 1)
    result = session.cached_preview(window.settings_panel.settings(), *calls[-1])
    np.testing.assert_array_equal(window.image_viewer.image_item.image, np.maximum(result, 0))


def test_measurement_box_requires_enable_and_uses_actual_drawing(window):
    """Bind the reused rectangle tool to image pixels without cropping processing."""
    canvas = window.image_viewer.canvas
    viewport = cast(QWidget, canvas.viewport())
    start = cast(QPoint, canvas.mapFromScene(window.image_viewer.view_box.mapViewToScene(QPointF(4, 3))))
    end = cast(QPoint, canvas.mapFromScene(window.image_viewer.view_box.mapViewToScene(QPointF(26, 25))))
    box = window.settings_panel.measurement
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    assert box.bounds is None
    box.enabled.setChecked(True)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(end), QPointF(viewport.mapToGlobal(end)),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, move)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    assert box.bounds is not None
    assert "Original mean:" in window.settings_panel.means.text()
    window._run_preview()
    wait_for_preview(window)
    assert window.image_viewer.image_item.image.shape == (32, 32)


def test_histogram_failure_shows_error_and_preserves_original(window, monkeypatch):
    """Keep invalid background estimates out of the display and report the cause."""
    from bg_sub import core

    def invalid_histogram(**kwargs):
        """Simulate the histogram failure reported by SciPy."""
        return np.divide(1.0, 0.0)

    monkeypatch.setattr(core, "SMO", invalid_histogram)
    window._run_preview()
    wait_for_preview(window)
    assert "valid background reference histogram" in window.status_label.text()
    assert not window._preview_enabled
    assert window.run_button.isEnabled()
    assert window.save_button.isEnabled()
    session = window._session
    assert session is not None and not session._previews
    original = session.display_frame(0, window.channel_combo.currentText(), 0)
    np.testing.assert_array_equal(window.image_viewer.image_item.image, original)


def test_close_waits_for_active_plane_before_releasing_session(window, monkeypatch):
    """Finish the active native SMO call before closing its session and thread."""
    session = window._session
    assert session is not None
    real_compute = session.compute_plane
    entered, release = Event(), Event()

    def compute(*args):
        """Keep one plane active until the close request has been handled."""
        entered.set()
        assert release.wait(5)
        return real_compute(*args)

    monkeypatch.setattr(session, "compute_plane", compute)
    window._run_preview()
    try:
        for _ in range(100):
            QTest.qWait(10)
            if entered.is_set():
                break
        assert entered.is_set()
        window.close()
        assert window.isVisible() and window._closing
    finally:
        release.set()
    wait_for_preview(window)
    assert not window.isVisible()
    assert window._session is None


@pytest.mark.parametrize("enabled", [False, True])
def test_gui_selected_experiment_settings_and_save_without_preview(source, tmp_path, enabled):
    """Lock directory browsing and retain step enablement on settings-only saves."""
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_step_enabled(StepName.BG_SUB, enabled)
    adapter.set_field_value(StepName.BG_SUB, "size", 5)
    adapter.set_field_value(StepName.BG_SUB, "sigma", 0.5)
    main = FitsMainWindow(adapter)
    try:
        main._open_background_tuner()
        tuner = main._background_tuner
        assert tuner is not None
        assert tuner._source_path == source
        assert tuner.directory_browser.selected_path == source
        assert tuner.settings_panel.window_size.value() == 5
        assert tuner.settings_panel.sigma.value() == 0.5
        assert not tuner.browse_button.isEnabled()
        assert not tuner.directory_edit.isEnabled()
        tuner.settings_panel.window_size.setValue(7)
        tuner.save_button.click()
        assert not tuner.isVisible()
        assert main.adapter.field_value(StepName.BG_SUB, "size") == 7
        assert main.adapter.step_enabled(StepName.BG_SUB) == enabled
        assert main._editors[StepName.BG_SUB].advanced_settings_visible
    finally:
        main.close()


def test_standalone_saves_settings_without_changing_pixels(source, tmp_path):
    """Keep standalone browsing and save to the usual general settings path."""
    original = source.read_bytes()
    viewer = BackgroundTunerWindow(tmp_path)
    viewer.show()
    try:
        assert viewer.browse_button.isEnabled()
        assert viewer.directory_edit.isEnabled()
        viewer.settings_panel.window_size.setValue(9)
        viewer.save_button.click()
        saved = load_settings(run_settings_path(tmp_path))
        assert saved["bg_sub"]["params"]["size"] == 9
        assert source.read_bytes() == original
        assert not viewer.isVisible()
    finally:
        viewer.close()


def test_help_lists_comparison_and_measurement_shortcuts(window):
    """Advertise the tuner-specific shortcut without a nonexistent mask toggle."""
    dialog = ViewerInformationDialog(window, title="BGTune", version="test", gui="BGTune")
    table = dialog.findChild(QTableWidget)
    assert table is not None
    shortcuts = []
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        assert item is not None
        shortcuts.append(item.text())
    assert "V" in shortcuts and "R" in shortcuts and "S" in shortcuts
    assert "X" not in shortcuts
    dialog.close()


def test_display_clamping_preserves_signed_input(window):
    """Show negative pixels as zero without changing the array used for analysis."""
    image = np.array([[-4.5, 2.25], [-1.0, 8.0]], dtype=np.float32)
    original = image.copy()
    image.setflags(write=False)
    window.image_viewer.set_image(image)
    displayed = window.image_viewer.image_item.image
    np.testing.assert_array_equal(displayed, [[0, 2.25], [0, 8]])
    np.testing.assert_array_equal(image, original)
    assert not np.shares_memory(displayed, image)
