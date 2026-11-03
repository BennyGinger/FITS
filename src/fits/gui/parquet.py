"""Open Parquet tables in the optional independent Tad application."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from fits.external_tools.tad import TAD_WEBSITE, launch_tad


def open_parquet(path: Path, parent: QWidget | None = None) -> None:
    """
    Launch Tad or explain how to install a table viewer without interrupting FITS.
    """
    root = Path(__file__).resolve().parents[3]
    try:
        launch_tad(root, path)
    except FileNotFoundError:
        message = QMessageBox(parent)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle('Tad is not installed')
        message.setTextFormat(Qt.TextFormat.RichText)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        message.setText(f'To view Parquet tables, install Tad from '
                        f'<a href="{TAD_WEBSITE}">{TAD_WEBSITE}</a>.<br><br>'
                        'Alternatively, open the file in VS Code using the Data Wrangler extension.'
                        '<br><br>FITS remains fully operational.')
        message.exec()
    except OSError as error:
        QMessageBox.warning(parent, 'Cannot open Tad', f'Tad could not be started: {error}\n\nFITS remains fully operational.')
