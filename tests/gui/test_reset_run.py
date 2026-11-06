"""Reset confirmation, cancellation, and replacement of the main GUI state."""

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import tifffile
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QDialog, QGroupBox, QLineEdit, QPushButton, QWidget

from fits.gui.file_management.reset import confirm_reset
from fits.gui.main import _run_gui
from fits.gui.main_window import FitsMainWindow
from fits.gui.settings import SettingsAdapter


@pytest.fixture
def app() -> QApplication:
    """
    Keep one application alive while testing modal confirmation and fresh windows.
    """
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    return application


def test_confirmation_requires_exact_reset(app: QApplication, tmp_path: Path) -> None:
    """
    A manual backup suggestion and disabled confirmation protect accidental clicks.
    """
    def inspect_confirmation() -> None:
        """
        Enter the required word only after checking the initial and incorrect states.
        """
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        text = dialog.findChild(QLineEdit, 'reset_confirmation')
        reset = dialog.findChild(QPushButton, 'confirm_reset')
        assert text is not None and reset is not None
        assert not reset.isEnabled()
        text.setText('reset')
        assert not reset.isEnabled()
        text.setText('RESET')
        assert reset.isEnabled()
        reset.click()

    QTimer.singleShot(0, inspect_confirmation)
    assert confirm_reset(tmp_path)
    def cancel_confirmation() -> None:
        """
        Close the confirmation without authorizing any reset.
        """
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.close()

    QTimer.singleShot(0, cancel_confirmation)
    assert not confirm_reset(tmp_path)


@pytest.fixture
def raw_run(tmp_path: Path) -> Path:
    """
    Create a portable acquisition with a cache and a valid raw TIFF for GUI discovery.
    """
    acquisition = tmp_path / 'control/sample'
    (acquisition / '.fits_experiment/cache').mkdir(parents=True)
    tifffile.imwrite(acquisition / 'sample.tif', np.ones((8, 8), dtype=np.uint16), photometric='minisblack')
    (acquisition / '.fits_experiment/cache/preview.npy').write_bytes(b'cached preview')
    return tmp_path


@pytest.mark.parametrize('confirmed', [False, True])
def test_manager_reset_requires_confirmation(app: QApplication,
                                            raw_run: Path,
                                            confirmed: bool,
                                            monkeypatch: pytest.MonkeyPatch,
                                            ) -> None:
    """
    The third section resets the whole run only after confirmation and manager closure.
    """
    from fits.gui.file_management.manager import manage_files
    calls: list[bool] = []

    def choose_reset(dialog: QDialog) -> int:
        """
        Inspect the section and press its single reset button.
        """
        group = dialog.findChild(QGroupBox, 'reset_to_raw')
        assert group is not None and group.title() == 'Reset to raw inputs'
        buttons = group.findChildren(QPushButton)
        assert len(buttons) == 1 and buttons[0].text() == 'Reset'
        buttons[0].click()
        return int(QDialog.DialogCode.Accepted if confirmed else QDialog.DialogCode.Rejected)

    def on_reset() -> None:
        """
        Record that the manager has closed before executing the destructive action.
        """
        calls.append(app.activeModalWidget() is None)

    monkeypatch.setattr(QDialog, 'exec', choose_reset)
    monkeypatch.setattr('fits.gui.file_management.manager.confirm_reset', lambda root, parent: confirmed)
    assert manage_files(raw_run, selected=raw_run / 'control/sample', reset_run=on_reset) is confirmed
    assert calls == ([True] if confirmed else [])


def test_reset_opens_fresh_window_with_same_run(app: QApplication,
                                             raw_run: Path,
                                             monkeypatch: pytest.MonkeyPatch,
                                             ) -> None:
    """
    Reset through Manage files replaces stale GUI settings without recreating run metadata.
    """
    windows: list[FitsMainWindow] = []

    class RecordingWindow(FitsMainWindow):
        def __init__(self, adapter: SettingsAdapter | None = None, **kwargs: Any) -> None:
            """
            Record actual windows while giving the initial window a run and user name.
            """
            if adapter is None:
                adapter = SettingsAdapter()
                adapter.run_dir = str(raw_run)
                adapter.user_name = ''
            super().__init__(adapter, **kwargs)
            windows.append(self)

    def accept_reset(*args: object, reset_run: Callable[[], None], **kwargs: object) -> bool:
        """
        Execute the action supplied after the manager's confirmation has succeeded.
        """
        assert windows[0].isVisible()
        reset_run()
        return True

    def inspect_event_loop(application: QApplication) -> int:
        """
        Trigger reset, then inspect the replacement before its event loop exits.
        """
        old = windows[0]
        old._append_log('Previous console message')
        old._manage_files()
        assert len(windows) == 2
        fresh = windows[1]
        assert fresh.isVisible() and not old.isVisible()
        assert fresh.adapter.run_dir == str(raw_run)
        assert fresh.adapter.user_name == ''
        assert fresh.console.toPlainText() == ''
        assert fresh.adapter.document == _template_document(fresh.adapter, raw_run)
        assert not fresh._prepared_available
        assert (raw_run / 'control/sample.tif').is_file()
        assert not (raw_run / '.fits').exists()
        assert not (raw_run / 'control/sample').exists()
        fresh.close()
        return 0

    monkeypatch.setattr('fits.gui.main_window.FitsMainWindow', RecordingWindow)
    monkeypatch.setattr('fits.gui.main_window.window.manage_files', accept_reset)
    monkeypatch.setattr(QApplication, 'exec', inspect_event_loop)
    with pytest.raises(SystemExit) as result:
        _run_gui(argparse.Namespace(demo_step_delay=0.0), [])
    assert result.value.code == 0


def _template_document(adapter: SettingsAdapter, root: Path) -> Any:
    """
    Return default settings with only the run directory and empty user identity applied.
    """
    template = SettingsAdapter(adapter.template_path)
    template.run_dir = str(root)
    template.user_name = ''
    return template.document


def test_cancelled_editor_close_preserves_run(app: QApplication,
                                            raw_run: Path,
                                            monkeypatch: pytest.MonkeyPatch,
                                            ) -> None:
    """
    Declining unsaved-editor closure prevents disk reset and window replacement.
    """
    class UnsavedEditor(QWidget):
        def closeEvent(self, event: QCloseEvent) -> None:
            """
            Simulate the user cancelling an unsaved-edit confirmation.
            """
            event.ignore()

    adapter = SettingsAdapter()
    adapter.run_dir = str(raw_run)
    adapter.user_name = 'User'
    window = FitsMainWindow(adapter)
    editor = UnsavedEditor()
    window._manual_tracking_editor = editor
    replacements: list[str] = []
    window.fresh_window_requested.connect(replacements.append)

    def reset_action(*args: object, reset_run: Callable[[], None], **kwargs: object) -> bool:
        """
        Invoke the confirmed reset with the unsaved editor still open.
        """
        reset_run()
        return True

    monkeypatch.setattr('fits.gui.main_window.window.manage_files', reset_action)
    try:
        window._manage_files()
        assert (raw_run / 'control/sample/sample.tif').is_file()
        assert not replacements
        assert 'Reset cancelled' in window.console.toPlainText()
    finally:
        window._manual_tracking_editor = None
        window.close()
        editor.deleteLater()
