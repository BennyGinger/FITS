from __future__ import annotations

import argparse
import sys
from pathlib import Path
from collections.abc import Callable
from PySide6.QtWidgets import QApplication, QMainWindow
from fisch.gui.theme import apply_dark_theme


def segtune() -> None:
    """
    Return the current segtune.
    """
    parser = argparse.ArgumentParser(description="Tune FIScH segmentation and compartment settings.")
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--tab", choices=("segmentation", "compartment"), default="segmentation")
    parser.add_argument("--experiments-dir", type=Path)
    arguments, qt_arguments = parser.parse_known_args()
    from fisch.gui.viewer.segmentation import SegmentationTunerWindow

    def create_window() -> QMainWindow:
        """
        Open the combined tuner on the requested processing tab.
        """
        root = arguments.experiments_dir
        if root is None and arguments.image is not None:
            root = arguments.image if arguments.image.is_dir() else arguments.image.parent
        return SegmentationTunerWindow(root, initial_path=arguments.image, initial_tab=arguments.tab)

    _launch(create_window, "FIScH Segmentation and Compartment Tuner", qt_arguments)


def regtune() -> None:
    """
    Return the current regtune.
    """
    parser = argparse.ArgumentParser(description="Tune FIScH time and channel registration.")
    parser.add_argument("image",
                        nargs="?",
                        type=Path,
                        help="A FIScH image artifact or an experiment folder to open.",
                        )
    parser.add_argument("--mode",
                        choices=("time", "channel"),
                        default="time",
                        help="Registration tab to select initially.",
                        )
    parser.add_argument("--experiments-dir", type=Path, help="Folder containing prepared experiments.")
    parser.add_argument("--settings", type=Path, help="General FIScH settings to load and update when saving.")
    arguments, qt_arguments = parser.parse_known_args()
    from fisch.gui.viewer.registration import RegistrationTunerWindow

    def create_window() -> QMainWindow:
        """
        Create the standalone viewer with the requested settings.
        """
        root = arguments.experiments_dir
        if root is None and arguments.image is not None:
            root = arguments.image if arguments.image.is_dir() else arguments.image.parent
        window = RegistrationTunerWindow(root,
                                         mode=arguments.mode,
                                         settings_path=arguments.settings,
                                         initial_path=arguments.image,
                                         )
        return window

    _launch(create_window, "FIScH Registration Tuner", qt_arguments)


def bgtune() -> None:
    """
    Launch on-demand background tuning with optional image and settings paths.
    """
    parser = argparse.ArgumentParser(description="Tune FIScH background subtraction on selected image planes.")
    parser.add_argument("image",
                        nargs="?",
                        type=Path,
                        help="A FIScH image artifact or experiment folder to open.",
                        )
    parser.add_argument("--experiments-dir", type=Path, help="Folder containing prepared experiments.")
    parser.add_argument("--settings", type=Path, help="FIScH settings to load and update on Save current settings.")
    arguments, qt_arguments = parser.parse_known_args()
    from fisch.gui.viewer.background import BackgroundTunerWindow

    def create_window() -> QMainWindow:
        """
        Resolve the standalone root while honoring an explicitly selected image.
        """
        root = arguments.experiments_dir
        if root is None and arguments.image is not None:
            root = arguments.image if arguments.image.is_dir() else arguments.image.parent
        return BackgroundTunerWindow(root, settings_path=arguments.settings, initial_path=arguments.image)

    _launch(create_window, "FIScH Background Subtraction Tuner", qt_arguments)


def trackedit() -> None:
    """
    Return the current trackedit.
    """
    parser = argparse.ArgumentParser(description="View and edit FIScH tracking labels.")
    parser.add_argument("tracking",
                        nargs="?",
                        type=Path,
                        help="A current tracking mask to edit, or a FIScH image artifact to start from scratch.",
                        )
    arguments, qt_arguments = parser.parse_known_args()
    from fisch.gui.viewer.tracking import TrackingViewerWindow

    _launch(lambda: TrackingViewerWindow(tracking_path=arguments.tracking, editing_enabled=True),
            "FIScH Tracking Viewer / Editor",
            qt_arguments,
            )


def trackviewer() -> None:
    """
    Return the current trackviewer.
    """
    parser = argparse.ArgumentParser(description="View raw ND2/TIFF inputs, FIScH images and masks.")
    parser.add_argument("tracking",
                        nargs="?",
                        type=Path,
                        help="Raw ND2/TIFF input or current, compacted or legacy FIScH image/mask to open.",
                        )
    parser.add_argument("--experiments-dir", type=Path, help="FIScH run directory.")
    arguments, qt_arguments = parser.parse_known_args()
    from fisch.gui.viewer.tracking import TrackingViewerWindow

    _launch(lambda: TrackingViewerWindow(experiments_dir=arguments.experiments_dir,
                                         tracking_path=arguments.tracking,
                                         editing_enabled=False,
                                         selection_enabled=True,
                                         ),
        "FIScH Tracking Viewer", qt_arguments)


def drawmask() -> None:
    """
    Return the current drawmask.
    """
    parser = argparse.ArgumentParser(description="Draw FIScH reference and ROI masks.")
    parser.add_argument("--tool", choices=("manual", "pipeline"), default="manual")
    parser.add_argument("--experiments-dir", type=Path, help="Folder containing prepared experiments.")
    parser.add_argument("--settings", type=Path, help="FIScH settings for the pipeline panel preview.")
    arguments, qt_arguments = parser.parse_known_args()
    if arguments.tool == "manual":
        from fisch.gui.viewer.masks import MaskDrawingWindow
        _launch(lambda: MaskDrawingWindow(arguments.experiments_dir), "FIScH Mask Drawing", qt_arguments)
        return
    from fisch.gui.viewer.masks import MaskCollectionWindow
    from fisch.gui.settings import SettingsAdapter
    from fisch.settings.models import DistanceProfileSettings, ExtractSettings

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

    def create_window() -> QMainWindow:
        """
        Create the standalone viewer with the requested settings.
        """
        window = MaskCollectionWindow(preview=True, extraction=extraction, profile=profile)
        if arguments.experiments_dir:
            window.load_test_experiments(arguments.experiments_dir)
        return window

    _launch(create_window, "FIScH Mask Collection Preview", qt_arguments)


def _launch(window_factory: Callable[[], QMainWindow], name: str, qt_arguments: list[str]) -> None:
    """
    Return the current launch.
    """
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([sys.argv[0], *qt_arguments])
    app.setApplicationName(name)
    apply_dark_theme(app)
    window = window_factory()
    window.show()
    raise SystemExit(app.exec())
