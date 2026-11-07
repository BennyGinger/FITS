"""Shared save/close appearance and unsaved-work confirmation for tuners."""

from collections.abc import Sequence

from PySide6.QtWidgets import QMessageBox, QWidget


RUN_PREVIEW_STYLE = (
    "QPushButton { background-color: #d97706; color: white; "
    "font-weight: bold; padding: 6px 12px; border-radius: 4px; } "
    "QPushButton:hover { background-color: #ea8a0c; } "
    "QPushButton:pressed { background-color: #b85f05; }")

SAVE_SETTINGS_STYLE = (
    "QPushButton { background-color: #16803b; color: white; "
    "font-weight: bold; padding: 7px 12px; border-radius: 4px; } "
    "QPushButton:hover { background-color: #1c9848; } "
    "QPushButton:pressed { background-color: #11652f; }")

CLOSE_WINDOW_STYLE = (
    "QPushButton { background-color: #e8a0a0; color: #301818; "
    "padding: 7px 12px; border-radius: 4px; } "
    "QPushButton:hover { background-color: #f0b4b4; } "
    "QPushButton:pressed { background-color: #d68c8c; }")


def confirm_discard_tuner_changes(parent: QWidget, tabs: Sequence[str]) -> bool:
    """Let users return to save individual tabs or explicitly discard their edits."""
    message = QMessageBox(parent)
    message.setWindowTitle("Unsaved tuner settings")
    message.setIcon(QMessageBox.Icon.Warning)
    message.setText("Unsaved changes in: " + ", ".join(tabs) + ".")
    message.setInformativeText(
        "Keep editing to save your changes with Save current settings, "
        "or close without saving these changes.")
    keep_editing = message.addButton("Keep editing", QMessageBox.ButtonRole.RejectRole)
    discard = message.addButton("Close without saving", QMessageBox.ButtonRole.DestructiveRole)
    message.setDefaultButton(keep_editing)
    message.setEscapeButton(keep_editing)
    message.exec()
    return message.clickedButton() is discard
