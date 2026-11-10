from __future__ import annotations

import sys
import argparse
from contextlib import nullcontext
import os
from pathlib import Path

from filelock import FileLock, Timeout


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the FIScH pipeline GUI.")
    parser.add_argument("--demo-step-delay", type=float, default=0.0, metavar="SECONDS",
                        help="Pause between interactive pipeline steps (try 5 seconds); default: no delay.")
    arguments, qt_arguments = parser.parse_known_args()
    if arguments.demo_step_delay < 0:
        parser.error("--demo-step-delay must be nonnegative")
    root = Path(__file__).resolve().parents[3]
    lock_path = Path(os.environ.get("FISCH_APPLICATION_LOCK", str(root / "startup/logs/application.lock")))
    # Register direct CLI launches too; an updater must never change their .venv.
    lock = FileLock(str(lock_path), timeout=0) if (root / ".git").exists() else nullcontext()
    try:
        with lock:
            _run_gui(arguments, qt_arguments)
    except Timeout:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.information(None, "FIScH is already open", "This FIScH checkout is already running or being updated.")


def _run_gui(arguments: argparse.Namespace, qt_arguments: list[str]) -> None:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from fisch.gui.theme import apply_dark_theme
    from fisch.gui.main_window import FischMainWindow
    from fisch.gui.settings import SettingsAdapter

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([sys.argv[0], *qt_arguments])
    app.setApplicationName("FIScH")
    app.setDesktopFileName("fisch")
    icon = Path(__file__).resolve().parents[3] / "assets" / "fisch_icon.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    apply_dark_theme(app)
    window = FischMainWindow(demo_step_delay=arguments.demo_step_delay)

    def fresh_window(root: str) -> None:
        """
        Replace the completed reset's window using template settings and fresh state.
        """
        nonlocal window
        previous = window
        adapter = SettingsAdapter(previous.adapter.template_path)
        adapter.run_dir = root
        adapter.user_name = ''
        window = FischMainWindow(adapter, demo_step_delay=arguments.demo_step_delay)
        window.fresh_window_requested.connect(fresh_window)
        window.setGeometry(previous.geometry())
        window.console.clear()
        window.show()
        previous.close()
        previous.deleteLater()

    window.fresh_window_requested.connect(fresh_window)
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
