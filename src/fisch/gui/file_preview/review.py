"""Pair concise visual file reviews with the complete textual execution plan."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QTabWidget, QWidget
from fisch.gui.dialogs import size_resizable_dialog


def size_file_review(dialog: QDialog) -> None:
    """
    Open file reviews as independently movable windows on the caller's screen.
    """
    screen = dialog.screen()
    dialog.setParent(None, Qt.WindowType.Window)
    if screen is not None:
        dialog.setScreen(screen)
    size_resizable_dialog(dialog, 1440, 900)


def review_tabs(preview: QWidget, details: str, title: str = 'File preview') -> QTabWidget:
    """
    Keep complete plan details accessible alongside a focused visual review.
    """
    tabs = QTabWidget()
    tabs.addTab(preview, title)
    text = QPlainTextEdit(details)
    text.setReadOnly(True)
    tabs.addTab(text, 'Full details')
    return tabs
