"""Reusable protocol export, transactional GUI loading and run settings backups."""

from __future__ import annotations

import os
from pathlib import Path
import tomllib

import numpy as np
import pytest
import tifffile
import tomlkit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QFileDialog, QMessageBox

from fisch.environment.constant import StepName, WORKFLOW_ORDER
from fisch.gui.main_window.window import FischMainWindow
from fisch.gui.settings import SettingsAdapter
from fisch.settings.loader import write_settings


@pytest.fixture
def app() -> QApplication:
    """
    Keep the Qt application alive throughout each GUI test.
    """
    instance = QApplication.instance()
    assert instance is None or isinstance(instance, QApplication)
    return instance or QApplication([])


def _protocol(path: Path, labels: list[str]) -> Path:
    """
    Write a protocol containing independent channel settings and overwrite requests.
    """
    adapter = SettingsAdapter()
    adapter.run_dir = "/old/run"
    adapter.user_name = "Old user"
    adapter.set_runtime_value("log_dir", "/old/logs")
    adapter.set_field_value(StepName.CONVERT, "channel_labels", labels)
    adapter.set_field_value(StepName.CONVERT, "export_channels", labels[:1] or "all")
    adapter.set_segment_channels([{"channel": label, "user_settings": {"model_type": "/models/custom", "diameter": 20 + index}}
                                  for index, label in enumerate(labels)])
    adapter.set_step_enabled(StepName.SEGMENT, bool(labels))
    for step in WORKFLOW_ORDER:
        adapter.set_field_value(step, "overwrite", True)
    return adapter.save(path)


def test_protocol_round_trip_preserves_paths_channels_and_current_identity(tmp_path: Path) -> None:
    """
    Strip run-specific fields without losing models, per-channel settings or draft identity.
    """
    original = _protocol(tmp_path / "original.toml", ["Green", "Red"])
    source = SettingsAdapter()
    source.load(original)
    document = source.protocol_document()
    assert "run_dir" not in document and "user_name" not in document
    assert "log_dir" not in document["runtime"]
    assert source.field_value(StepName.SEGMENT, "overwrite") is True
    protocol = write_settings(tmp_path / "protocol.toml", tomlkit.dumps(document))
    current = SettingsAdapter()
    current.run_dir = str(tmp_path)
    current.user_name = "Current user"
    current.set_runtime_value("log_dir", "/current/logs")
    candidate = current.protocol_candidate(protocol)
    assert candidate.run_dir == current.run_dir
    assert candidate.user_name == "Current user"
    assert candidate.runtime_value("log_dir") == "/current/logs"
    assert candidate.source_channel_labels() == ["Green", "Red"]
    assert [entry["user_settings"]["diameter"] for entry in candidate.segment_channels()] == [20, 21]
    assert candidate.segment_channels()[0]["user_settings"]["model_type"] == "/models/custom"
    assert all(candidate.field_value(step, "overwrite") is False for step in WORKFLOW_ORDER)


def test_run_settings_backup_only_when_saved_content_changes(tmp_path: Path) -> None:
    """
    Retain prior saved contents once, with no backup merely for loading a draft.
    """
    current = SettingsAdapter()
    current.run_dir = str(tmp_path)
    destination = current.save_to_run_dir()
    previous = destination.read_bytes()
    current.save_to_run_dir()
    history = destination.parent / "settings_history"
    assert not history.exists()
    protocol = _protocol(tmp_path / "protocol.toml", ["Green", "Red"])
    candidate = current.protocol_candidate(protocol)
    assert destination.read_bytes() == previous
    assert not history.exists()
    candidate.save_to_run_dir()
    assert [path.read_bytes() for path in history.glob("*.toml")] == [previous]
    assert tomllib.loads(destination.read_text())["convert"]["params"]["channel_labels"] == ["Green", "Red"]


def test_protocol_buttons_follow_run_selection_and_processing(app: QApplication, tmp_path: Path) -> None:
    """
    Replace manual settings loading and gate both protocol actions on an idle run.
    """
    window = FischMainWindow()
    try:
        assert not hasattr(window, "load_button")
        assert not window.load_protocol_button.isEnabled()
        assert not window.save_protocol_button.isEnabled()
        window._switch_run_dir(str(tmp_path))
        assert window.load_protocol_button.isEnabled()
        assert window.save_protocol_button.isEnabled()
        window._set_running(True)
        assert not window.load_protocol_button.isEnabled()
        assert not window.save_protocol_button.isEnabled()
        window._set_running(False)
        window.run_dir_edit.clear()
        assert not window.load_protocol_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


@pytest.mark.parametrize("choice", ["Continue", "Cancel", "mismatch", "invalid"])
def test_loading_protocol_is_transactional(app: QApplication, tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch, choice: str,
                                         ) -> None:
    """
    Apply only validated confirmed settings and never save the run during loading.
    """
    run = tmp_path / "run"
    run.mkdir()
    tifffile.imwrite(run / "input.tif", np.zeros((2, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={"axes": "CYX"},
                     )
    labels = ["Green", "Red", "Blue"] if choice == "mismatch" else ["Green", "Red"]
    protocol = _protocol(tmp_path / "protocol.toml", labels)
    if choice == "invalid":
        protocol.write_text("[invalid TOML")
    current = SettingsAdapter()
    current.run_dir = str(run)
    current.user_name = "Current user"
    current.set_runtime_value("log_dir", "/current/logs")
    current.set_field_value(StepName.CONVERT, "channel_labels", ["Before", "Other"])
    destination = current.save_to_run_dir()
    previous = destination.read_bytes()
    window = FischMainWindow(current)
    app.processEvents()
    warnings: list[str] = []
    confirmations: list[str] = []

    def pick_file(*args: object, **kwargs: object) -> tuple[str, str]:
        """
        Verify that the protocol browser filters TOML files.
        """
        assert args[3] == "TOML protocols (*.toml)"
        return str(protocol), ""

    def confirm(dialog: QMessageBox) -> int:
        """
        Simulate the requested confirmation, verifying Cancel is the default.
        """
        assert dialog.defaultButton().text() == "Cancel"
        confirmations.append(dialog.text())
        selected = 'Cancel' if choice == 'mismatch' else choice
        next(button for button in dialog.buttons() if button.text() == selected).click()
        return 0

    monkeypatch.setattr(QFileDialog, "getOpenFileName", pick_file)
    monkeypatch.setattr(QMessageBox, "exec", confirm)
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warnings.append(text))
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: warnings.append(text))
    try:
        window.load_protocol_button.click()
        assert destination.read_bytes() == previous
        assert not (destination.parent / "settings_history").exists()
        if choice == "Continue":
            assert window.adapter.source_channel_labels() == ["Green", "Red"]
            assert window.adapter.user_name == "Current user"
            assert window.adapter.runtime_value("log_dir") == "/current/logs"
            assert window.adapter.run_dir == str(run)
            assert window.adapter.field_value(StepName.CONVERT, "export_channels") == ["Green"]
            assert not window.adapter.field_value(StepName.SEGMENT, "overwrite")
            assert "source channel order: Green, Red" in window.console.toPlainText()
        else:
            assert window.adapter is current
            assert window.adapter.source_channel_labels() == ["Before", "Other"]
        # Label-count differences are warnings with reader-label fallback,
        # rather than invalid protocols. Cancelling still preserves the draft.
        assert bool(confirmations) == (choice != "invalid")
    finally:
        window.close()
        app.processEvents()


def test_save_protocol_uses_gui_draft_without_saving_run(app: QApplication, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      ) -> None:
    """
    Export user-selected TOML without changing the saved run or overwrite checkboxes.
    """
    current = SettingsAdapter()
    current.run_dir = str(tmp_path)
    destination = current.save_to_run_dir()
    previous = destination.read_bytes()
    window = FischMainWindow(current)
    app.processEvents()
    protocol = tmp_path / "export.toml"

    def save_dialog(browser: QFileDialog) -> int:
        """
        Verify the suffix is set before the browser performs overwrite confirmation.
        """
        assert browser.defaultSuffix() == "toml"
        assert browser.nameFilters() == ["TOML protocols (*.toml)"]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QFileDialog, "exec", save_dialog)
    monkeypatch.setattr(QFileDialog, "selectedFiles", lambda self: [str(protocol)])
    try:
        window.user_name_edit.setText("New user")
        overwrite = window._editors[StepName.CONVERT].widgets["overwrite"]
        assert isinstance(overwrite, QCheckBox)
        overwrite.setChecked(True)
        window.save_protocol_button.click()
        saved = tomllib.loads(protocol.read_text())
        assert "user_name" not in saved and "run_dir" not in saved
        assert "log_dir" not in saved["runtime"]
        assert saved["convert"]["params"]["overwrite"] is False
        assert current.field_value(StepName.CONVERT, "overwrite") is True
        assert destination.read_bytes() == previous
    finally:
        window.close()
        app.processEvents()
