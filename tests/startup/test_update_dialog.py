"""The startup prompt uses only Qt and closes before updating .venv."""

import importlib
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])


@pytest.fixture
def dialog_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "startup"))
    return importlib.import_module("update_dialog")


def test_update_prompt_choices_and_window_close_default(dialog_module):
    dialog = dialog_module.UpdateDialog({"kind": "update", "message": "FITS update available"})
    assert dialog.action == "current"
    assert dialog.buttons["current"].text() == "Use current version"
    dialog.buttons["update"].click()
    assert dialog.action == "update"
    dialog.close()


def test_dirty_checkout_disables_update_but_allows_current(dialog_module):
    dialog = dialog_module.UpdateDialog({"kind": "update", "message": "Local edits", "blocked": True})
    assert not dialog.buttons["update"].isEnabled()
    assert dialog.buttons["current"].isEnabled()
    dialog.buttons["current"].click()
    assert dialog.action == "current"
    dialog.close()


def test_repair_prompt_does_not_silently_accept(dialog_module):
    dialog = dialog_module.UpdateDialog({"kind": "repair", "message": "Repair needed"})
    assert dialog.action == "cancel"
    dialog.buttons["repair"].click()
    assert dialog.action == "repair"
    dialog.close()
