from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from fits.gui.theme import apply_dark_theme
from fits.gui.viewer.window import FitsViewerWindow, ViewerTool


def _arguments() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Open the FITS image viewer.")
    parser.add_argument(
        "--tool",
        choices=("segmentation", "reference-mask", "all"),
        default="segmentation",
        help=("Tool shown at startup. 'all' exposes every tool and is intended "
              "for development."),)
    arguments, qt_arguments = parser.parse_known_args()
    return arguments, qt_arguments


def main() -> None:
    arguments, qt_arguments = _arguments()
    tool: ViewerTool = arguments.tool
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_arguments])
    app.setApplicationName("FITS Viewer")
    apply_dark_theme(app)
    window = FitsViewerWindow(tool=tool)
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
