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
from fits.gui.viewer.common.tuner_actions import CLOSE_WINDOW_STYLE, RUN_PREVIEW_STYLE, SAVE_SETTINGS_STYLE
from fits.settings.loader import load_settings, run_settings_path
from fits.settings.models import BGSubSettings

_APP = None


@pytest.fixture(autouse=True)
def application():
    """Keep one application alive across isolated offscreen viewer tests."""
    global _APP
    _APP = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def discard_unsaved_settings(monkeypatch):
    """Keep unrelated test cleanup from waiting on an unsaved-settings dialog."""
    monkeypatch.setattr('fits.gui.viewer.background.window.confirm_discard_tuner_changes',
                        lambda parent, tabs: True)


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
    window.settings_panel.window_size.setValue(5)
    window._run_preview()
    try:
        for _ in range(100):
            QTest.qWait(10)
            if entered.is_set():
                break
        assert entered.is_set()
        monkeypatch.setattr('fits.gui.viewer.background.window.confirm_discard_tuner_changes',
                            lambda parent, tabs: False)
        window.close_button.click()
        assert window.isVisible() and not window._closing
        assert window._thread is not None
        monkeypatch.setattr('fits.gui.viewer.background.window.confirm_discard_tuner_changes',
                            lambda parent, tabs: True)
        window.close_button.click()
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
        assert tuner.isVisible()
        assert not tuner._has_unsaved_settings()
        assert main.adapter.field_value(StepName.BG_SUB, "size") == 7
        assert main.adapter.step_enabled(StepName.BG_SUB) == enabled
        assert not main._editors[StepName.BG_SUB].advanced_settings_visible
        main.adapter.set_field_value(StepName.BG_SUB, 'size', 9)
        assert tuner._has_unsaved_settings()
        main.adapter.set_field_value(StepName.BG_SUB, 'size', 7)
        assert not tuner._has_unsaved_settings()
    finally:
        if main._background_tuner is not None:
            main._background_tuner.close()
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
        assert viewer.isVisible()
        assert not viewer._has_unsaved_settings()
    finally:
        viewer.close()


def test_shared_action_layout_and_save_shortcut_stay_open(window):
    """Use registration's button styles/order and let S save without closing."""
    actions = window.session_actions.layout()
    assert [actions.itemAt(i).widget() for i in range(3)] == [
        window.run_button, window.save_button, window.close_button]
    assert [button.text() for button in (window.run_button, window.save_button, window.close_button)] == [
        'Run preview', 'Save current settings', 'Close window']
    assert window.run_button.styleSheet() == RUN_PREVIEW_STYLE
    assert window.save_button.styleSheet() == SAVE_SETTINGS_STYLE
    assert window.close_button.styleSheet() == CLOSE_WINDOW_STYLE
    accepted = []
    window.settings_applied.connect(accepted.append)
    window.settings_panel.sigma.setValue(0.5)
    window.image_viewer.setFocus()
    QTest.keyClick(window.image_viewer, Qt.Key.Key_S)
    assert window.isVisible()
    assert len(accepted) == 1 and accepted[0].sigma == 0.5
    assert not window._has_unsaved_settings()
    assert 'Saved background' in window.status_label.text()


@pytest.mark.parametrize('title_bar', [False, True])
def test_close_warns_and_discard_never_saves(window, monkeypatch, title_bar):
    """Both close paths let users return to save or explicitly discard processing edits."""
    accepted, prompts = [], []
    window.settings_applied.connect(accepted.append)
    window.settings_panel.window_size.setValue(7)
    def keep_editing(parent, tabs):
        prompts.append(tabs)
        return False
    monkeypatch.setattr('fits.gui.viewer.background.window.confirm_discard_tuner_changes', keep_editing)
    close = window.close if title_bar else window.close_button.click
    close()
    assert window.isVisible() and window._session is not None
    assert prompts == [['Background subtraction']]
    assert not accepted
    monkeypatch.setattr('fits.gui.viewer.background.window.confirm_discard_tuner_changes',
                        lambda parent, tabs: True)
    close()
    assert not window.isVisible() and window._session is None
    assert not accepted


def test_saved_and_measurement_only_changes_close_without_warning(window, monkeypatch):
    """Measurement geometry and viewing controls are temporary, not unsaved processing work."""
    prompts = []
    monkeypatch.setattr('fits.gui.viewer.background.window.confirm_discard_tuner_changes',
                        lambda parent, tabs: prompts.append(tabs) or False)
    window.settings_panel.window_size.setValue(7)
    window.save_button.click()
    window.settings_panel.window_size.setValue(9)
    assert window._has_unsaved_settings()
    window.settings_panel.window_size.setValue(7)
    assert not window._has_unsaved_settings()
    window.settings_panel.measurement.enabled.setChecked(True)
    window.settings_panel.measurement.set_bounds((4, 3, 26, 25))
    window.channel_combo.setCurrentIndex(1)
    window.close_button.click()
    assert not window.isVisible()
    assert prompts == []


@pytest.mark.parametrize('field,value', [
    ('window_size', 9), ('sigma', 0.5), ('threshold', 0.2),
    ('statistic', 'mean'), ('overwrite', True), ('excluded', True),
])
def test_processing_controls_participate_in_unsaved_check(window, field, value):
    """Track every editable processing setting, including overwrite and channel exclusions."""
    widget = getattr(window.settings_panel, field)
    if field == 'statistic':
        widget.setCurrentText(value)
    elif field == 'overwrite':
        widget.setChecked(value)
    elif field == 'excluded':
        widget.item(0).setCheckState(Qt.CheckState.Checked)
    else:
        widget.setValue(value)
    assert window._has_unsaved_settings()
    window.save_button.click()
    assert not window._has_unsaved_settings()


def test_failed_save_keeps_changes_and_viewer_open(source, monkeypatch):
    """A failed standalone write leaves the saved baseline intact and still warns on close."""
    viewer = BackgroundTunerWindow(source.parent)
    viewer.show()
    try:
        viewer.settings_panel.window_size.setValue(9)
        def fail_save(path):
            raise OSError('Cannot write settings')
        monkeypatch.setattr(viewer._general_adapter, 'save', fail_save)
        viewer.save_button.click()
        assert viewer.isVisible()
        assert viewer._has_unsaved_settings()
        assert 'Cannot write settings' in viewer.status_label.text()
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


def test_c_cycles_included_background_channels_and_keeps_excluded_channels_selectable(window, monkeypatch):
    """Skip exclusions for C, with safe behavior for one or no active channels."""
    monkeypatch.setattr(window, 'isActiveWindow', lambda: True)
    window.activateWindow()
    window.image_viewer.setFocus()
    QTest.keyClick(window.image_viewer, Qt.Key.Key_C)
    assert window.channel_combo.currentIndex() == 1
    QTest.keyClick(window.image_viewer, Qt.Key.Key_C)
    assert window.channel_combo.currentIndex() == 0
    window.settings_panel.excluded.item(1).setCheckState(Qt.CheckState.Checked)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_C)
    assert window.channel_combo.currentIndex() == 0
    window.channel_combo.setCurrentIndex(1)
    assert window.channel_combo.currentIndex() == 1
    QTest.keyClick(window.image_viewer, Qt.Key.Key_C)
    assert window.channel_combo.currentIndex() == 0
    window.settings_panel.excluded.item(0).setCheckState(Qt.CheckState.Checked)
    QTest.keyClick(window.image_viewer, Qt.Key.Key_C)
    assert window.channel_combo.currentIndex() == 0


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
