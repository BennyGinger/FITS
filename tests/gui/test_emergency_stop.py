"""Exercise confirmation and emergency shutdown without exiting pytest."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter


@pytest.mark.parametrize("confirm", [False, True])
def test_stop_requires_confirmation(monkeypatch: pytest.MonkeyPatch, confirm: bool) -> None:
    """
    Keep Stop enabled during execution and terminate only after confirmation.
    """
    app = QApplication.instance() or QApplication([])
    window = FitsMainWindow(SettingsAdapter())
    stopped: list[bool] = []

    def confirm_stop(*args: object) -> QMessageBox.StandardButton:
        """
        Verify the safe default and return the requested answer.
        """
        assert args[1] == "Stop and exit FITS?"
        assert args[-1] == QMessageBox.StandardButton.No
        return QMessageBox.StandardButton.Yes if confirm else QMessageBox.StandardButton.No

    def record_stop() -> None:
        """
        Record shutdown without terminating the test runner.
        """
        stopped.append(True)

    monkeypatch.setattr(QMessageBox, "warning", confirm_stop)
    monkeypatch.setattr("fits.gui.main_window.window.terminate_application", record_stop)
    try:
        app.processEvents()
        assert window.stop_button.isEnabled()
        window._set_running(True)
        assert window.stop_button.isEnabled()
        assert not window.run_button.isEnabled()
        window.stop_button.click()
        assert stopped == ([True] if confirm else [])
    finally:
        window._set_running(False)
        window.close()


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
        assert application.returncode == 1
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
