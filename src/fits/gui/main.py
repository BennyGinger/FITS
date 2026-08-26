from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from fits.gui.theme import apply_dark_theme
from fits.gui.window import FitsMainWindow


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("FITS")
    apply_dark_theme(app)
    window = FitsMainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
