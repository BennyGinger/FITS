"""Standalone compatibility wrapper around the embedded channel-label panel."""

from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from fisch.gui.channel_labels.panel import ChannelLabelsPanel
from fisch.gui.help.dialog import info_button, show_help


class ChannelLabelsWindow(QMainWindow):
    """Keep the standalone launcher using the same editor as Manage files."""

    def __init__(self, run_dir: str | Path, parent: QWidget | None = None) -> None:
        """
        Wrap the reusable editor without duplicating its file operations.
        """
        super().__init__(parent)
        self.setWindowTitle("FIScH channel labels")
        self.resize(850, 360)
        host = QWidget()
        layout = QVBoxLayout(host)
        header = QHBoxLayout()
        header.addStretch()
        self.info_button = info_button()
        self.info_button.clicked.connect(lambda: show_help(self, title="Channel labels", gui="Channel labels",
                                                         guide_page="tools/channel_labels.md"))
        header.addWidget(self.info_button)
        layout.addLayout(header)
        self.panel = ChannelLabelsPanel(run_dir)
        layout.addWidget(self.panel)
        self.setCentralWidget(host)

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Keep workers alive until their file operation finishes.
        """
        if self.panel.is_busy:
            event.ignore()
            return
        self.panel.finish_session()
        super().closeEvent(event)
