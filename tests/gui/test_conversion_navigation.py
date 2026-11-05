"""Convert/processing navigation uses successful conversion settings only."""

import os
from pathlib import Path
from typing import cast
from time import monotonic, sleep

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from fits.environment.constant import StepName
from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.workflows.runtime.progress import StageStatus, WorkflowStage

_APP = None


@pytest.fixture
def window(tmp_path, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "Test"
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["Red"])
    monkeypatch.setattr("fits.gui.main_window.window.choose_artifacts", lambda report, parent=None, **kwargs: "rebuild")
    main = FitsMainWindow(adapter)
    _APP.processEvents()
    yield main
    if main._worker is not None:
        main._worker.interaction.cancel()
        wait_for_run(main)
    main.close()
    main.deleteLater()
    _APP.processEvents()


def wait_for_run(window: FitsMainWindow) -> None:
    """
    Pump GUI events while giving the Python pipeline worker time to execute.
    """
    deadline = monotonic() + 15
    while window._thread is not None and monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(5)
        sleep(0.001)
    assert window._thread is None, "Pipeline worker did not finish"


@pytest.mark.parametrize("channels", [1, 2])
def test_expected_channels_uses_all_raw_files(window: FitsMainWindow, tmp_path: Path, channels: int) -> None:
    """
    Show the raw channel count independently of user labels and exported channels.
    """
    for name in ("first.tif", "second.tiff"):
        tifffile.imwrite(tmp_path / name, np.zeros((channels, 8, 8), dtype=np.uint16),
                         imagej=True, metadata={"axes": "CYX"})
    window._refresh_run_inventory()
    hint = window._editors[StepName.CONVERT].expected_channels_label
    noun = "channel" if channels == 1 else "channels"
    assert hint.text() == f"({channels} expected {noun})"
    assert hint.font().italic()
    assert not window._raw_input_error()
    assert window.run_button.isEnabled()
    assert bool(window._channel_label_warning()) == (channels != 1)
    for path in tmp_path.glob("*.tif*"):
        path.unlink()
    window._refresh_run_inventory()
    assert hint.isHidden()


def test_mixed_raw_channel_counts_block_conversion(window: FitsMainWindow,
                                                  tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  ) -> None:
    """
    Warn and prevent pipeline launch when raw acquisitions have different channel counts.
    """
    for channels in (1, 2):
        tifffile.imwrite(tmp_path / f"input_{channels}.tif", np.zeros((channels, 8, 8), dtype=np.uint16),
                         imagej=True, metadata={"axes": "CYX"})
    window._refresh_run_inventory()
    hint = window._editors[StepName.CONVERT].expected_channels_label
    assert hint.text() == "(different channel counts: 1 or 2)"
    assert not window.run_button.isEnabled()
    assert "Cannot convert" in window.navigation_status.text()
    assert "input_1.tif: 1 channel" in window.file_status_label.toolTip()
    assert "input_2.tif: 2 channels" in window._file_details_text()
    assert "#e57373" in window.file_status_label.styleSheet()
    assert "#e57373" in window.navigation_status.styleSheet()
    assert not window._channel_label_warning()
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, message: warnings.append(message))
    monkeypatch.setattr(window, "_save_settings", lambda: pytest.fail("Mixed channel counts reached pipeline setup"))
    window._launch_pipeline(convert_only=True)
    assert len(warnings) == 1
    assert "different numbers of channels (1, 2)" in warnings[0]
    assert window._thread is None
    (tmp_path / "input_2.tif").unlink()
    window._refresh_run_inventory()
    assert hint.text() == "(1 expected channel)"
    assert window.run_button.isEnabled()


def test_label_count_warning_is_orange_nonblocking_and_clears_after_edit(window: FitsMainWindow,
                                                                        tmp_path: Path,
                                                                        ) -> None:
    """
    Show exact fallback labels in orange without blocking conversion or repeating unchanged warnings.
    """
    tifffile.imwrite(tmp_path / "input.tif", np.zeros((3, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={"axes": "CYX"})
    window._refresh_run_inventory()
    editor = window._editors[StepName.CONVERT]
    field = cast(QLineEdit, editor.widgets["channel_labels"])
    field.setText("Red, Green")
    field.editingFinished.emit()
    message = window._channel_label_warning()
    assert "Expected 3 channels, got 2 channel labels" in message
    assert "default names: C_1, C_2, C_3." in message
    assert not window._raw_input_error()
    assert window.run_button.isEnabled()
    assert "#efb366" in window.navigation_status.styleSheet()
    assert "#efb366" in editor.expected_channels_label.styleSheet()
    assert message in window._file_details_text()
    assert window.console.toPlainText().count(message) == 1
    assert window.console.textCursor().charFormat().foreground().color().name() == "#efb366"
    window._update_run_button_text()
    assert window.console.toPlainText().count(message) == 1
    window._append_log("Normal log message")
    assert window.console.textCursor().charFormat().foreground().color().name() != "#efb366"
    field.setText("Red, Green, Blue")
    field.editingFinished.emit()
    assert not window._channel_label_warning()
    assert "#efb366" not in window.navigation_status.styleSheet()
    assert not editor.expected_channels_label.styleSheet()
    assert window.run_button.isEnabled()


def test_duplicate_stems_load_without_popup(window: FitsMainWindow,
                                           tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch,
                                           ) -> None:
    """
    Treat automatically resolved same-folder stems as valid inputs without a popup.
    """
    for extension in ("tif", "tiff"):
        tifffile.imwrite(tmp_path / f"sample.{extension}", np.zeros((2, 8, 8), dtype=np.uint16),
                         imagej=True, metadata={"axes": "CYX"})
    window.adapter.set_field_value(StepName.CONVERT, "channel_labels", ["Red", "Green"])
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail("Unexpected input warning popup"))
    window._refresh_run_inventory()
    assert not window._raw_input_error()
    assert window.run_button.isEnabled()
    assert not (tmp_path / "sample_tif").exists()
    assert window._raw_input_report is not None
    assert window._raw_input_report.acquisition_directories[tmp_path / "sample.tif"] == tmp_path / "sample_tif"


def test_destination_conflict_identifies_input_in_red(window: FitsMainWindow, tmp_path: Path) -> None:
    """
    Show a blocking destination conflict and its source file through shared inspection.
    """
    tifffile.imwrite(tmp_path / "sample.tif", np.zeros((8, 8), dtype=np.uint16), metadata={"axes": "YX"})
    (tmp_path / "sample").mkdir()
    window._refresh_run_inventory()
    assert not window.run_button.isEnabled()
    assert "Cannot create acquisition folder: sample" in window.navigation_status.text()
    assert "sample.tif" in window._file_details_text()
    assert "#e57373" in window.file_status_label.styleSheet()


def test_next_converts_once_then_unchanged_back_next_only_navigates(window, tmp_path, monkeypatch):
    tifffile.imwrite(tmp_path / "acquisition.tif", np.arange(64, dtype=np.uint16).reshape(8, 8),
                     photometric="minisblack", metadata={"axes": "YX"})
    # The first page must not validate or execute unconfigured later steps.
    window._editors[StepName.SEGMENT].enable_group.setChecked(True)
    assert window.run_button.isEnabled()
    failures = []
    monkeypatch.setattr(window, "_pipeline_failed", lambda message, details: failures.append(details))
    window.run_button.click()
    assert window._worker.convert_only
    assert not window._worker.force_conversion
    assert not window.back_button.isEnabled()
    wait_for_run(window)
    assert not failures
    assert list(tmp_path.rglob("fits_array_raw.tif"))
    assert window.workflow_pages.currentIndex() == 1
    assert window._current_step == StepName.REGISTER_TIME
    assert window.adapter.step_enabled(StepName.SEGMENT)

    window._back_to_convert()
    with monkeypatch.context() as context:
        context.setattr(window, "_launch_pipeline", lambda **kwargs: pytest.fail("Unchanged Next reran conversion"))
        window.run_button.click()
    assert window.workflow_pages.currentIndex() == 1

    # An explicit overwrite change requests one new conversion, not every Next.
    window._back_to_convert()
    window._editors[StepName.CONVERT].widgets["overwrite"].setChecked(True)
    window.run_button.click()
    assert window._worker.force_conversion
    wait_for_run(window)
    assert not failures
    assert window.workflow_pages.currentIndex() == 1
    window._back_to_convert()
    with monkeypatch.context() as context:
        context.setattr(window, "_launch_pipeline", lambda **kwargs: pytest.fail("Unchanged overwrite reran conversion"))
        window.run_button.click()
    assert window.workflow_pages.currentIndex() == 1


def test_changed_conversion_settings_force_rebuild_without_changing_overwrite(window, tmp_path, monkeypatch):
    (tmp_path / "fits_array.tif").touch()
    window._populate_from_adapter()
    # Simulate reopening this prepared run with the current conversion settings.
    window._converted_settings = window._conversion_signature()
    window._back_to_convert()
    field = window._editors[StepName.CONVERT].widgets["channel_labels"]
    field.setText("FarRed")
    field.editingFinished.emit()
    captured = []

    def convert(**kwargs):
        captured.append(kwargs)
        kwargs["run_progress"].add("experiment", {WorkflowStage.CONVERT})
        kwargs["run_progress"].update("experiment", WorkflowStage.CONVERT, StageStatus.COMPLETED)

    monkeypatch.setattr("fits.gui.main_window.pipeline_worker.start_pipeline", convert)
    window.run_button.click()
    assert window._worker.force_conversion
    wait_for_run(window)
    assert captured[0]["convert_only"]
    assert captured[0]["force_conversion"]
    assert window.adapter.field_value(StepName.CONVERT, "overwrite") is False
    assert window.workflow_pages.currentIndex() == 1


@pytest.mark.parametrize("outcome", ["failure", "cancel", "no_conversion", "changed_while_running"])
def test_unsuccessful_or_changed_conversion_does_not_advance(window, tmp_path, monkeypatch, outcome):
    (tmp_path / "fits_array.tif").touch()
    window._refresh_phase_access()
    window._converted_settings = window._conversion_signature()
    window._editors[StepName.CONVERT].widgets["overwrite"].setChecked(True)
    failures = []
    monkeypatch.setattr(window, "_pipeline_failed", lambda message, details: failures.append(message))

    def convert(**kwargs):
        if outcome == "failure":
            raise RuntimeError("conversion failed")
        if outcome == "cancel":
            from fits.workflows.runtime.interactive import PipelineCancelled
            raise PipelineCancelled()
        if outcome == "changed_while_running":
            kwargs["run_progress"].add("experiment", {WorkflowStage.CONVERT})
            kwargs["run_progress"].update("experiment", WorkflowStage.CONVERT, StageStatus.COMPLETED)

    monkeypatch.setattr("fits.gui.main_window.pipeline_worker.start_pipeline", convert)
    window.run_button.click()
    if outcome == "changed_while_running":
        field = window._editors[StepName.CONVERT].widgets["channel_labels"]
        field.setText("Changed")
        field.editingFinished.emit()
    wait_for_run(window)
    assert window.workflow_pages.currentIndex() == 0
    assert not window._conversion_is_current()
    assert bool(failures) == (outcome == "failure")


def test_processing_run_uses_normal_pipeline(window, tmp_path, monkeypatch):
    (tmp_path / "fits_array.tif").touch()
    window._refresh_phase_access()
    window._converted_settings = window._conversion_signature()
    window._next_from_convert()
    captured = []
    monkeypatch.setattr("fits.gui.main_window.pipeline_worker.start_pipeline", lambda **kwargs: captured.append(kwargs))
    window.run_button.click()
    assert not window._worker.convert_only
    assert not window._worker.force_conversion
    wait_for_run(window)
    assert not captured[0]["convert_only"]
    assert not captured[0]["force_conversion"]


def test_selecting_saved_converted_run_opens_processing_with_loaded_settings(window, tmp_path):
    root = tmp_path / "saved_run"
    root.mkdir()
    (root / "fits_array.tif").touch()
    saved = SettingsAdapter()
    saved.run_dir = str(root)
    saved.set_field_value(StepName.CONVERT, "channel_labels", ["FarRed"])
    saved.set_field_value(StepName.CONVERT, "overwrite", True)
    saved.save_to_run_dir()

    window._switch_run_dir(str(root))
    QApplication.processEvents()
    assert window.workflow_pages.currentIndex() == 1
    assert window._current_step == StepName.REGISTER_TIME
    assert window._conversion_is_current()
    window._back_to_convert()
    window._next_from_convert()
    assert window.workflow_pages.currentIndex() == 1
    assert window._thread is None


@pytest.fixture(autouse=True)
def isolate_settings_navigation_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Isolate navigation/settings tests from metadata checks on empty image fixtures.
    """
    from fits.workflows.checks.models import RunCompatibility
    monkeypatch.setattr('fits.gui.main_window.window.inspect_run_compatibility',
        lambda root: RunCompatibility(Path(root).resolve(), (), (), (), ()))
