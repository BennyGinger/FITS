"""Short-lived Qt choices, run in .venv and closed before packages are changed."""

import argparse
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QHBoxLayout, QVBoxLayout


class UpdateDialog(QDialog):
    def __init__(self, request: dict) -> None:
        super().__init__()
        self.action = "current" if request["kind"] == "update" else "cancel"
        self.setWindowTitle(request.get("title", "FITS"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        message = QLabel(request["message"])
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setWordWrap(True)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(message)
        row = QHBoxLayout()
        row.addStretch()
        self.buttons = {}
        if request["kind"] == "update":
            choices = [("current", "Use current version"), ("update", "Update FITS")]
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
        self.buttons[choices[0][0]].setDefault(True)
        layout.addLayout(row)

    def choose(self, action: str) -> None:
        self.action = action
        self.accept()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("response", type=Path)
    arguments = parser.parse_args()
    app = QApplication([])
    app.setApplicationName("FITS")
    request = json.loads(arguments.request.read_text(encoding="utf-8"))
    dialog = UpdateDialog(request)
    dialog.exec()
    arguments.response.write_text(json.dumps({"action": dialog.action}), encoding="utf-8")


if __name__ == "__main__":
    main()
