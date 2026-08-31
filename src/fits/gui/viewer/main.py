from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from fits.gui.theme import apply_dark_theme
from fits.gui.viewer.window import FitsViewerWindow


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("FITS Viewer")
    apply_dark_theme(app)
    window = FitsViewerWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
