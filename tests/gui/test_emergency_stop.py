"""Exercise confirmation and emergency shutdown without exiting pytest."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.gui.main_window.pipeline_worker import PipelineWorker
from fits.gui.main_window.stop_dialog import QUIT_STYLE
from fits.gui.viewer.common.tuner_actions import CLOSE_WINDOW_STYLE, SAVE_SETTINGS_STYLE


@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize('action', ['stop', 'quit', 'close'])
def test_stop_and_quit_require_confirmation(monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path,
                                           confirm: bool,
                                           action: str,
                                           ) -> None:
    """
    Stop only the run, or quit the application, using coloured icon-free confirmation.
    """
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    window = FitsMainWindow(SettingsAdapter())
    stopped: list[bool] = []
    worker = PipelineWorker(tmp_path / 'settings.toml', logging.NullHandler())
    window._worker = worker

    def choose() -> None:
        """
        Inspect the actual confirmation and click its explicit safe or destructive choice.
        """
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        assert dialog.windowTitle() == ('Stop run?' if action == 'stop' else 'Quit FITS?')
        assert 'Overwrite' in dialog.informativeText()
        no = dialog.button(QMessageBox.StandardButton.No)
        yes = dialog.button(QMessageBox.StandardButton.Yes)
        assert dialog.defaultButton() is no
        assert no.styleSheet() == SAVE_SETTINGS_STYLE
        assert yes.styleSheet() == QUIT_STYLE
        assert no.icon().isNull() and yes.icon().isNull()
        (yes if confirm else no).click()

    def record_stop() -> None:
        """
        Record shutdown without terminating the test runner.
        """
        stopped.append(True)

    monkeypatch.setattr("fits.gui.main_window.window.terminate_application", record_stop)
    try:
        app.processEvents()
        window.show()
        assert not window.stop_button.isEnabled()
        assert window.quit_button.isEnabled()
        assert window.stop_button.text() == 'Stop run'
        assert window.stop_button.styleSheet() == CLOSE_WINDOW_STYLE
        assert window.quit_button.text() == 'Quit'
        window._set_running(True)
        assert window.stop_button.isEnabled()
        assert not window.run_button.isEnabled()
        QTimer.singleShot(0, choose)
        if action == 'close':
            window.close()
        else:
            (window.stop_button if action == 'stop' else window.quit_button).click()
        assert stopped == ([True] if confirm and action != 'stop' else [])
        assert worker.interaction.cancelled.is_set() == (confirm and action == 'stop')
        assert window.isVisible()
    finally:
        window._worker = None
        window._set_running(False)
        window.close()


def test_idle_quit_closes_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Quit without a running pipeline behaves like the ordinary window close button.
    """
    app = QApplication.instance() or QApplication([])
    window = FitsMainWindow(SettingsAdapter())
    window.show()
    app.processEvents()
    monkeypatch.setattr('fits.gui.main_window.window.confirm_stop',
                        lambda *args, **kwargs: pytest.fail('Idle quit must not ask to terminate processing.'))
    window.quit_button.click()
    assert not window.isVisible()


def test_emergency_stop_kills_descendants_and_busy_threads(tmp_path: Path) -> None:
    """
    Stop a disposable application with a child, grandchild and busy thread.
    """
    ready = tmp_path / "ready.json"
    stop = tmp_path / "stop"
    child_code = (
        "import subprocess, sys, time\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(grandchild.pid, flush=True)\n"
        "time.sleep(120)\n"
    )
    application_code = (
        "import json, subprocess, sys, threading, time\n"
        "from pathlib import Path\n"
        "from fits.gui.main_window.emergency_stop import terminate_application\n"
        "threading.Thread(target=time.sleep, args=(120,)).start()\n"
        "child = subprocess.Popen([sys.executable, '-c', sys.argv[3]], stdout=subprocess.PIPE, text=True)\n"
        "grandchild_pid = int(child.stdout.readline())\n"
        "Path(sys.argv[1]).write_text(json.dumps([child.pid, grandchild_pid]))\n"
        "while not Path(sys.argv[2]).exists():\n"
        "    time.sleep(0.02)\n"
        "terminate_application()\n"
    )
    application = subprocess.Popen([sys.executable, "-c", application_code, str(ready), str(stop), child_code],
                                   env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   )
    descendants: list[psutil.Process] = []
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and application.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "Disposable application did not become ready."
        descendants = [psutil.Process(pid) for pid in json.loads(ready.read_text())]
        stop.touch()
        application.communicate(timeout=10)
        assert application.returncode == 0
        # Orphaned zombies can await reaping by the host; they execute no work.
        assert all(not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
                   for process in descendants)
    finally:
        if application.poll() is None:
            descendants.extend(psutil.Process(application.pid).children(recursive=True))
            application.kill()
        for process in descendants:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        application.communicate(timeout=10)
