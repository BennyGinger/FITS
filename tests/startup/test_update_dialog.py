"""The startup prompt uses only Qt and closes before updating .venv."""

import importlib
from pathlib import Path
from types import ModuleType

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])


@pytest.fixture
def dialog_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """
    Load the standalone Qt startup dialog without importing FIScH.
    """
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "startup"))
    return importlib.import_module("update_dialog")


def test_update_prompt_choices_and_window_close_default(dialog_module: ModuleType) -> None:
    """
    Offer Yes and Skip while retaining the current version by default.
    """
    dialog = dialog_module.UpdateDialog({"kind": "update", "release": "4.4.4", "current_version": "4.3.3", "message": "FIScH update available"})
    assert dialog.action == "current"
    assert dialog.buttons["current"].text() == "Skip"
    assert dialog.buttons["update"].text() == "Yes"
    assert dialog.buttons["current"].isDefault()
    dialog.buttons["update"].click()
    assert dialog.action == "update"
    dialog.close()


def test_dirty_checkout_disables_update_but_allows_current(dialog_module: ModuleType) -> None:
    """
    Keep Skip available when local changes prevent an automatic update.
    """
    dialog = dialog_module.UpdateDialog({"kind": "update", "release": "4.4.4", "current_version": "4.3.3", "message": "Local edits", "blocked": True})
    assert not dialog.buttons["update"].isEnabled()
    assert dialog.buttons["current"].isEnabled()
    dialog.buttons["current"].click()
    assert dialog.action == "current"
    dialog.close()


def test_repair_prompt_does_not_silently_accept(dialog_module: ModuleType) -> None:
    """
    Preserve the repair prompt's explicit opt-in behavior.
    """
    dialog = dialog_module.UpdateDialog({"kind": "repair", "message": "Repair needed"})
    assert dialog.action == "cancel"
    dialog.buttons["repair"].click()
    assert dialog.action == "repair"
    dialog.close()


def test_release_details_expand_downward_and_collapse(dialog_module: ModuleType) -> None:
    """
    Start compact, render the release body, and expand below the prompt on demand.
    """
    description = "## Changes\n\n" + "- Improved tracking and image processing.\n" * 80
    dialog = dialog_module.UpdateDialog({"kind": "update", "release": "4.4.4", "current_version": "4.3.3",
                                         "message": "FIScH 5.1.0 is available. You are currently using 5.0.0.\n\nWould you like to update?",
                                         "details": description,
                                         })
    dialog.show()
    QApplication.processEvents()
    try:
        assert dialog.height() == dialog.layout().totalHeightForWidth(dialog.width())
        assert dialog.width() == dialog.minimumWidth()
        assert "<b>4.4.4</b>" in dialog.version_message.text()
        assert "<b>4.3.3</b>" in dialog.version_message.text()
        assert dialog.question.alignment() == Qt.AlignmentFlag.AlignRight
        collapsed_height = dialog.height()
        width, position = dialog.width(), dialog.pos()
        assert not dialog.details.isVisible()
        assert not dialog.details_toggle.isChecked()
        assert dialog.details_toggle.text() == "Details ▾"
        dialog.details_toggle.click()
        QApplication.processEvents()
        assert dialog.details.isVisible()
        assert dialog.details_toggle.text() == "Details ▴"
        assert "Improved tracking and image processing." in dialog.details.toPlainText()
        assert dialog.height() > collapsed_height
        assert dialog.width() == width
        assert dialog.pos() == position
        assert dialog.details.verticalScrollBar().maximum() > 0
        assert dialog.details.geometry().bottom() < dialog.buttons["update"].geometry().top()
        dialog.details_toggle.click()
        QApplication.processEvents()
        assert dialog.height() == collapsed_height
        assert dialog.pos() == position
        assert not dialog.details.isVisible()
    finally:
        dialog.close()
