from __future__ import annotations

import sys
import argparse

from PySide6.QtWidgets import QApplication

from fits.gui.theme import apply_dark_theme
from fits.gui.window import FitsMainWindow


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the FITS pipeline GUI.")
    parser.add_argument("--demo-step-delay", type=float, default=0.0, metavar="SECONDS",
                        help="Pause between interactive pipeline steps (try 5 seconds); default: no delay.")
    arguments, qt_arguments = parser.parse_known_args()
    if arguments.demo_step_delay < 0:
        parser.error("--demo-step-delay must be nonnegative")
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([sys.argv[0], *qt_arguments])
    app.setApplicationName("FITS")
    apply_dark_theme(app)
    window = FitsMainWindow(demo_step_delay=arguments.demo_step_delay)
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
