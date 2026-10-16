"""Standalone channel-label editor launcher."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from fits.gui.channel_labels import ChannelLabelsWindow
from fits.gui.theme import apply_dark_theme


def main() -> None:
    parser = argparse.ArgumentParser(description="Rename channel labels in a FITS run.")
    parser.add_argument("run_dir", type=Path)
    arguments, qt_arguments = parser.parse_known_args()
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([sys.argv[0], *qt_arguments])
    apply_dark_theme(app)
    window = ChannelLabelsWindow(arguments.run_dir)
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
