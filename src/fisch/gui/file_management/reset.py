"""Explicit confirmation for the irreversible whole-run reset."""

from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget
from fisch.gui.dialogs import size_resizable_dialog


def confirm_reset(root: Path, parent: QWidget | None = None) -> bool:
    """
    Require an explicit RESET after explaining the scope and manual backup option.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle('Reset to raw inputs — cannot be undone')
    layout = QVBoxLayout(dialog)
    warning = QLabel('This permanently resets the WHOLE run directory, including every experiment.\n\n'
                     'Original acquisitions will be moved out of their portable folders. All FIScH results, '
                     'drawn masks, measurements, settings, logs, caches and FIScH backup history will be deleted.\n\n'
                     'This cannot be undone. FIScH will not create a backup. '
                     'If you want to keep anything, cancel and make a manual backup first.\n\n'
                     'FIScH will then open a fresh window for this run with template settings and an empty user name.')
    warning.setWordWrap(True)
    layout.addWidget(warning)
    location = QLabel(str(root))
    location.setWordWrap(True)
    layout.addWidget(location)
    layout.addWidget(QLabel('Type RESET to confirm:'))
    text = QLineEdit()
    text.setObjectName('reset_confirmation')
    layout.addWidget(text)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    reset = buttons.addButton('Reset', QDialogButtonBox.ButtonRole.AcceptRole)
    reset.setObjectName('confirm_reset')
    reset.setStyleSheet('color: #ff5555;')
    reset.setEnabled(False)
    reset.setAutoDefault(False)
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
    text.textChanged.connect(lambda value: reset.setEnabled(value == 'RESET'))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    size_resizable_dialog(dialog, 620, 360)
    return dialog.exec() == QDialog.DialogCode.Accepted and text.text() == 'RESET'
