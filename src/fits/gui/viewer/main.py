from __future__ import annotations

import argparse
import sys
from pathlib import Path
from collections.abc import Callable

from PySide6.QtWidgets import QApplication, QMainWindow

from fits.gui.theme import apply_dark_theme


def segtune() -> None:
    parser = argparse.ArgumentParser(description="Tune FITS segmentation settings.")
    _, qt_arguments = parser.parse_known_args()
    from fits.gui.viewer.segmentation_window import SegmentationTunerWindow

    _launch(SegmentationTunerWindow, "FITS Segmentation Tuner", qt_arguments)


def drawmask() -> None:
    parser = argparse.ArgumentParser(description="Draw FITS reference and ROI masks.")
    parser.add_argument("--tool", choices=("manual", "pipeline"), default="manual")
    parser.add_argument("--experiments-dir", type=Path, help="Folder containing prepared experiments.")
    parser.add_argument("--settings", type=Path, help="FITS settings for the pipeline panel preview.")
    arguments, qt_arguments = parser.parse_known_args()
    if arguments.tool == "manual":
        from fits.gui.viewer.mask_window import MaskDrawingWindow
        _launch(lambda: MaskDrawingWindow(arguments.experiments_dir), "FITS Mask Drawing", qt_arguments)
        return
    from fits.gui.viewer.collection_window import MaskCollectionWindow
    from fits.gui.settings_adapter import SettingsAdapter
    from fits.settings.models import DistanceProfileSettings, ExtractSettings

    # Without a settings file, preview the usual distance-profile request: one reference.
    extraction = None
    profile = DistanceProfileSettings()
    if arguments.settings:
        adapter = SettingsAdapter()
        adapter.load(arguments.settings)
        values = adapter.as_mapping()
        extraction = (ExtractSettings.model_validate(values["extract"]["params"])
                      if values["extract"]["enabled"] else None)
        profile = (DistanceProfileSettings.model_validate(values["distance_profile"]["params"])
                   if values["distance_profile"]["enabled"] else None)

    def create_window():
        window = MaskCollectionWindow(preview=True, extraction=extraction, profile=profile)
        if arguments.experiments_dir:
            window.load_test_experiments(arguments.experiments_dir)
        return window

    _launch(create_window, "FITS Mask Collection Preview", qt_arguments)


def _launch(window_factory: Callable[[], QMainWindow], name: str,
            qt_arguments: list[str]) -> None:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([sys.argv[0], *qt_arguments])
    app.setApplicationName(name)
    apply_dark_theme(app)
    window = window_factory()
    window.show()
    raise SystemExit(app.exec())
