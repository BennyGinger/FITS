"""Common window sizing for scrollable reports and artifact previews."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog


def size_resizable_dialog(dialog: QDialog, width: int, height: int) -> None:
    """
    Expose resize/maximize controls and fit the initial window to its screen.
    """
    dialog.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
    dialog.setSizeGripEnabled(True)
    parent = dialog.parentWidget()
    screen = parent.screen() if parent is not None else dialog.screen()
    if screen is not None:
        available = screen.availableGeometry()
        width = min(width, int(available.width() * .85))
        height = min(height, int(available.height() * .85))
    dialog.setMinimumSize(min(420, width), min(300, height))
    dialog.resize(width, height)
