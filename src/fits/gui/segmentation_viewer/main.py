from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from fits.gui.segmentation_viewer.window import SegmentationViewerWindow
from fits.gui.theme import apply_dark_theme


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("FITS Segmentation Viewer")
    apply_dark_theme(app)
    window = SegmentationViewerWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
