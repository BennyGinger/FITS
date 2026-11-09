"""Explicit, consistently coloured confirmation for interrupting a run."""

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMessageBox, QWidget

from fits.gui.viewer.common.tuner_actions import SAVE_SETTINGS_STYLE


QUIT_STYLE = (
    'QPushButton { background-color: #b32632; color: white; border: 1px solid #dc4652; '
    'border-radius: 4px; padding: 6px 16px; font-weight: bold; }'
    'QPushButton:hover { background-color: #cf3040; }'
    'QPushButton:pressed { background-color: #8d1d27; }')


def confirm_stop(parent: QWidget, *, quitting: bool) -> bool:
    """
    Explain interruption and make the safe No answer green and Yes red, without icons.
    """
    dialog = QMessageBox(parent)
    dialog.setWindowTitle('Quit FITS?' if quitting else 'Stop run?')
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setText('Stop processing and quit FITS now?' if quitting else 'Stop the current run and keep FITS open?')
    dialog.setInformativeText('Processing will be interrupted. Restarting this run may require enabling Overwrite '
                              'for the affected steps.' + (' Unsaved GUI edits will be lost.' if quitting else ''))
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    dialog.setDefaultButton(QMessageBox.StandardButton.No)
    dialog.setEscapeButton(QMessageBox.StandardButton.No)
    for role, style in ((QMessageBox.StandardButton.No, SAVE_SETTINGS_STYLE),
                         (QMessageBox.StandardButton.Yes, QUIT_STYLE)):
        button = dialog.button(role)
        button.setIcon(QIcon())
        button.setStyleSheet(style)
    return dialog.exec() == QMessageBox.StandardButton.Yes
