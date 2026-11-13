"""Embedded channel-label inspection, confirmation and run-wide writes."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import numpy as np
import pytest
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from pytest import MonkeyPatch
from scope_io import ScopeIO

from fisch.environment.constant import StepName, ARTI_IMG
from fisch.workflows.experiments import ExperimentState, save_experiment_state
from datetime import datetime, timezone
from dataclasses import replace
from fisch.gui.channel_labels.panel import ChannelLabelsPanel
from fisch.gui.file_management.manager import _FileManagerDialog
from fisch.gui.help.dialog import HelpDialog
from fisch.gui.main_window.window import FischMainWindow
from fisch.gui.run_result.report import ReportDialog
from fisch.gui.segmentation_models.loader import ModelOptionsLoader
from fisch.gui.settings import SettingsAdapter
from fisch.gui.settings.conversion_channels import ConversionChannelsWidget
from fisch.settings.loader import run_settings_path


@pytest.fixture(scope="module", autouse=True)
def finish_model_discovery() -> Iterator[None]:
    """
    Retain Qt and finish shared model discovery before application teardown.
    """
    app = cast(QApplication, QApplication.instance() or QApplication([]))
    yield
    loader = app.findChild(ModelOptionsLoader, "fisch-cellpose-model-options")
    if loader is not None:
        loader.wait()


def _wait(predicate: Callable[[], bool]) -> None:
    """
    Process queued worker results until the expected state is reached.
    """
    app = cast(QApplication, QApplication.instance())
    for _ in range(1000):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    assert predicate()


def _run(root: Path, labels: list[str]) -> Path:
    """
    Create a tiny converted run for real metadata rename tests.
    """
    experiment = root / "experiment"
    experiment.mkdir()
    source = experiment / "input.tif"
    pixels = np.zeros((2, len(labels), 8, 9) if len(labels) > 1 else (2, 8, 9), dtype=np.uint8)
    tifffile.imwrite(source, pixels, imagej=True, metadata={"axes": "TCYX" if len(labels) > 1 else "TYX"})
    series = experiment / "input_s1"
    series.mkdir()
    reader = ScopeIO.from_path(source)
    payload = reader.build_payload(channel_labels=labels, export_channels="all",
                                   custom_metadata={"pipeline_meta": {"version": "5.0.0"}})
    payload = replace(payload, artifact=replace(payload.artifact,
                                                created_at=datetime.now(timezone.utc).isoformat(),
                                                derived_from=[{"artifact_path": str(source), "external": True}]))
    array = reader.save_array(pixels, metadata=payload, output_path=series / "proc_array.tif")
    state = ExperimentState.init(series, source, run_dir=root).with_complete_step(
        step_name=StepName.CONVERT, artifact_kind=ARTI_IMG, artifact_path=array)
    save_experiment_state(state)
    settings = run_settings_path(root)
    settings.parent.mkdir()
    settings.write_text('[convert.params]\nchannel_labels = ' + repr(labels).replace("'", '"') + '\n')
    return array


def test_convert_opens_manager_and_applies_confirmed_labels(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Both entry points use the same inline editor and update the active settings.
    """
    array = _run(tmp_path, ["GFP"])
    adapter = SettingsAdapter()
    adapter.load(run_settings_path(tmp_path))
    adapter.run_dir = str(tmp_path)
    window = FischMainWindow(adapter)
    opened: list[str] = []

    def _manager_exec(dialog: QDialog) -> int:
        """
        Exercise the inline editor while the manager owns its worker lifetime.
        """
        assert isinstance(dialog, _FileManagerDialog)
        editor = dialog.channel_editor
        assert editor is not None
        _wait(lambda: not editor.is_busy and editor.status.text() != "Inspecting channel labels…")
        assert editor.plan is not None, editor.files.toPlainText()
        opened.append(dialog.windowTitle())
        assert editor.channels.table.columnCount() == 3
        item = editor.channels.table.item(0, 2)
        assert item is not None
        item.setText("Green")
        assert "proc_array.tif" in editor.files.toPlainText()
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
        editor.save()
        assert ScopeIO.from_path(array).channel_labels == ["GFP"]
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Save)
        editor.save()
        assert editor.is_busy
        dialog.reject()
        assert editor.is_busy
        _wait(lambda: editor.plan is not None and editor.plan.labels == ((0, "Green"),) and not editor.is_busy)
        return QDialog.DialogCode.Rejected

    def _unexpected_report(dialog: ReportDialog) -> int:
        """
        Fail visibly instead of blocking on an unexpected maintenance error dialog.
        """
        raise AssertionError(dialog.details.toPlainText())

    monkeypatch.setattr(ReportDialog, "exec", _unexpected_report)
    monkeypatch.setattr(_FileManagerDialog, "exec", _manager_exec)
    try:
        assert not hasattr(window, "channel_labels_button")
        assert window.extra_tools.title() == "Extra tools"
        assert window.run_browser.title_layout.indexOf(window.report_button) >= 0
        channels = window._editors[StepName.CONVERT].widgets["channel_labels"]
        assert isinstance(channels, ConversionChannelsWidget)
        assert channels.manage_button is not None and channels.manage_button.isEnabled()
        window._editors[StepName.CONVERT].enable_group.setChecked(False)
        assert channels.manage_button.isEnabled()
        window._show_step(StepName.TRACK)
        window.info_button.click()
        help_window = window.findChild(HelpDialog, "fischHelpWindow")
        assert help_window is not None
        assert help_window.tabs.currentIndex() == 0
        assert help_window.guide.browser.source().fileName() == "tracking.md"
        window._show_step(StepName.SEGMENT)
        assert help_window.guide.browser.source().fileName() == "tracking.md"
        help_window.close()
        window._back_to_convert()
        channels.manage_button.click()
        assert opened == ["Manage experiment files"]
        assert ScopeIO.from_path(array).channel_labels == ["Green"]
        assert window.adapter.document["convert"]["params"]["channel_labels"] == ["Green"]
    finally:
        window.close()


def test_editor_previews_only_files_with_changed_channel(tmp_path: Path) -> None:
    """
    Renaming one channel does not include masks from an unrelated channel.
    """
    array = _run(tmp_path, ["BFP", "RFP"])
    ScopeIO.from_path(array).save_array(np.zeros((2, 8, 9), dtype=np.uint8), export_channels=["RFP"],
                                       output_path=array.parent / "proc_masks_seg.tif")
    editor = ChannelLabelsPanel(tmp_path)
    try:
        _wait(lambda: not editor.is_busy and editor.status.text() != "Inspecting channel labels…")
        assert editor.plan is not None, editor.files.toPlainText()
        item = editor.channels.table.item(0, 2)
        assert item is not None
        item.setText("Blue")
        preview = editor.files.toPlainText()
        assert "proc_array.tif" in preview
        assert "settings.toml" in preview
        assert "proc_masks_seg.tif" not in preview
        assert editor.save_button.isEnabled()
        item = editor.channels.table.item(0, 2)
        assert item is not None
        item.setText("")
        assert not editor.save_button.isEnabled()
    finally:
        _wait(lambda: not editor.is_busy)
        editor.close()


def test_editor_keeps_inspection_failure_visible(tmp_path: Path) -> None:
    """
    Failed inspection leaves the explanatory panel usable and saving disabled.
    """
    editor = ChannelLabelsPanel(tmp_path)
    editor.show()
    try:
        _wait(lambda: editor.status.text() == "Could not inspect channel labels." and not editor.is_busy)
        assert editor.isVisible()
        assert "No FIScH TIFFs" in editor.files.toPlainText()
        assert not editor.save_button.isEnabled()
    finally:
        _wait(lambda: not editor.is_busy)
        editor.close()
