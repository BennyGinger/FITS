"""Short-lived Qt choices, run in .venv and closed before packages are changed."""

import argparse
from html import escape
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QHBoxLayout, QTextBrowser, QToolButton, QVBoxLayout


class UpdateDialog(QDialog):
    def __init__(self, request: dict) -> None:
        """
        Build a compact startup prompt with release details hidden initially.
        """
        super().__init__()
        self.action = "current" if request["kind"] == "update" else "cancel"
        self.setWindowTitle(request.get("title", "FIScH"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        if request["kind"] == "update":
            self._add_update_message(layout, request)
            self._add_details(layout, request.get("details") or "No release description was provided.")
        else:
            message = QLabel(request["message"])
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setWordWrap(True)
            message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(message)
        row = QHBoxLayout()
        row.addStretch()
        self.buttons = {}
        if request["kind"] == "update":
            choices = [("update", "Yes"), ("current", "Skip")]
        elif request["kind"] == "repair":
            choices = [("cancel", "Close"), ("repair", "Repair and launch")]
        else:
            choices = [("cancel", "Close")]
        for action, title in choices:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, value=action: self.choose(value))
            if action == "update" and request.get("blocked"):
                button.setEnabled(False)
            row.addWidget(button)
            self.buttons[action] = button
        self.buttons[self.action].setDefault(True)
        layout.addLayout(row)
        self._resize_to_contents(self.minimumWidth())

    def _add_update_message(self, layout: QVBoxLayout, request: dict) -> None:
        """
        Emphasize version numbers and align the update question above the buttons.
        """
        self.version_message = QLabel(f"A newer version of FIScH is available: <b>{escape(request['release'])}</b>.<br>"
                                      f"The current version installed is <b>{escape(request['current_version'])}</b>.")
        self.version_message.setTextFormat(Qt.TextFormat.RichText)
        self.version_message.setWordWrap(True)
        self.version_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.version_message)
        if request.get("blocked_reason"):
            warning = QLabel(request["blocked_reason"])
            warning.setTextFormat(Qt.TextFormat.PlainText)
            warning.setWordWrap(True)
            layout.addWidget(warning)
        self.question = QLabel("Would you like to update?")
        self.question.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.question)

    def _resize_to_contents(self, width: int) -> None:
        """
        Fit wrapped content to the actual width instead of Qt's narrow size hint.
        """
        self.ensurePolished()
        layout = self.layout()
        if layout is not None:
            layout.activate()
            height = layout.totalHeightForWidth(width)
            if height < 0:
                height = layout.totalSizeHint().height()
            self.resize(width, height)

    def _add_details(self, layout: QVBoxLayout, description: str) -> None:
        """
        Match the File Manager disclosure and display the release's Markdown body.
        """
        self.details_toggle = QToolButton()
        self.details_toggle.setText("Details ▾")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setAutoRaise(True)
        self.details_toggle.setStyleSheet("text-align: left; color: #b8b8b8; font-style: italic;")
        layout.addWidget(self.details_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.details = QTextBrowser()
        self.details.setMarkdown(description)
        self.details.setOpenExternalLinks(True)
        self.details.setMinimumHeight(160)
        self.details.setMaximumHeight(260)
        self.details.hide()
        layout.addWidget(self.details)
        self.details_toggle.toggled.connect(self._toggle_details)

    def _toggle_details(self, expanded: bool) -> None:
        """
        Resize downward when showing details and restore the compact prompt on close.
        """
        position = self.pos()
        width = self.width()
        self.details.setVisible(expanded)
        self.details_toggle.setText("Details ▴" if expanded else "Details ▾")
        self._resize_to_contents(width)
        self.move(position)

    def choose(self, action: str) -> None:
        """
        Return the selected startup action to the independent launcher.
        """
        self.action = action
        self.accept()


def main() -> None:
    """
    Show a startup request and save the chosen action before exiting Qt.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("response", type=Path)
    arguments = parser.parse_args()
    app = QApplication([])
    app.setApplicationName("FIScH")
    request = json.loads(arguments.request.read_text(encoding="utf-8"))
    dialog = UpdateDialog(request)
    dialog.exec()
    arguments.response.write_text(json.dumps({"action": dialog.action}), encoding="utf-8")


if __name__ == "__main__":
    main()
