"""Shared save/close appearance and unsaved-work confirmation for tuners."""

from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QSizePolicy, QWidget


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

MAIN_GUI_SETTINGS_HINT = (
    "Updates the main GUI's editable settings without saving its settings file. "
    "Use Save settings or Run pipeline in the main GUI to save these changes to disk.")


def configure_tuner_window(window: QWidget, status_label: QLabel) -> None:
    """
    Open a wide, screen-height tuner and keep status text within its layout.
    """
    available = window.screen().availableGeometry()
    window.resize(min(1800, available.width()), available.height())
    status_label.setWordWrap(True)
    status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)


def set_preview_choices(combo: QComboBox, available: bool, original_index: int) -> None:
    """
    Keep preview choices visible but disabled until a matching preview is available.
    """
    model = combo.model()
    assert isinstance(model, QStandardItemModel)
    for index in range(combo.count()):
        item = model.item(index)
        assert item is not None
        item.setEnabled(available or index == original_index)
    if not available:
        with QSignalBlocker(combo):
            combo.setCurrentIndex(original_index)
    combo.setToolTip(combo.currentData(Qt.ItemDataRole.ToolTipRole))


def toggle_preview_choice(combo: QComboBox) -> None:
    """
    Toggle before/after views only when the destination choice is enabled.
    """
    target = 1 if combo.currentIndex() != 1 else 0
    model = combo.model()
    if model.flags(model.index(target, 0)) & Qt.ItemFlag.ItemIsEnabled:
        combo.setCurrentIndex(target)


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
