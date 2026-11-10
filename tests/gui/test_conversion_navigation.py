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

from fisch.environment.constant import StepName
from fisch.gui.main_window.window import FischMainWindow
from fisch.gui.settings.conversion_channels import ConversionChannelsWidget
from fisch.gui.settings import SettingsAdapter
from fisch.workflows.runtime.progress import StageStatus, WorkflowStage

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
    monkeypatch.setattr("fisch.gui.main_window.window.choose_artifacts", lambda report, parent=None, **kwargs: "rebuild")
    main = FischMainWindow(adapter)
    _APP.processEvents()
    yield main
    if main._worker is not None:
        main._worker.interaction.cancel()
        wait_for_run(main)
    main.close()
    main.deleteLater()
    _APP.processEvents()


def wait_for_run(window: FischMainWindow) -> None:
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
def test_expected_channels_uses_all_raw_files(window: FischMainWindow, tmp_path: Path, channels: int) -> None:
    """
    Convey the raw channel count through table rows and reserve the hint for warnings.
    """
    for name in ("first.tif", "second.tiff"):
        tifffile.imwrite(tmp_path / name, np.zeros((channels, 8, 8), dtype=np.uint16),
                         imagej=True, metadata={"axes": "CYX"})
    window._refresh_run_inventory()
    hint = window._editors[StepName.CONVERT].expected_channels_label
    table = cast(ConversionChannelsWidget, window._editors[StepName.CONVERT].widgets["channel_labels"])
    assert table.table.rowCount() == channels
    assert hint.text() == ("Channel label count mismatch" if channels != 1 else "")
    assert hint.isHidden() == (channels == 1)
    assert hint.font().italic()
    assert not window._raw_input_error()
    assert window.file_frames_label.text() == "<u>Frames:</u> 1"
    assert window.run_button.isEnabled()
    assert bool(window._channel_label_warning()) == (channels != 1)
    for path in tmp_path.glob("*.tif*"):
        path.unlink()
    window._refresh_run_inventory()
    assert hint.isHidden()
    assert window.file_frames_label.text() == "<u>Frames:</u> —"


def test_incompatible_steps_warn_on_activation_and_block_launch(window: FischMainWindow,
                                                               tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch,
                                                               ) -> None:
    """
    Warn once on activation and stop before saving or starting invalid processing.
    """
    tifffile.imwrite(tmp_path / "input.tif", np.zeros((2, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={"axes": "CYX"})
    window._refresh_run_inventory()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail("Unexpected validation popup"))
    monkeypatch.setattr(window, "_save_settings", lambda: pytest.fail("Incompatible steps reached pipeline setup"))
    for step in (StepName.TRACK, StepName.REGISTER_TIME):
        toggle = window._editors[step].enable_group
        toggle.setChecked(True)
        message = window._step_input_problems()[step]
        assert window.console.toPlainText().count(message) == 1
        assert "⚠ WARNING |" in window.console.toPlainText()
        assert window.console.textCursor().charFormat().foreground().color().name() == "#efb366"
        window._update_run_button_text()
        assert window.console.toPlainText().count(message) == 1
        window._launch_pipeline(convert_only=False)
        assert "✖ ERROR | " + message in window.console.toPlainText()
        assert window.console.textCursor().charFormat().foreground().color().name() == "#e57373"
        assert window._thread is None
        toggle.setChecked(False)


def test_frame_summary_and_single_channel_registration_guard(window: FischMainWindow, tmp_path: Path) -> None:
    """
    Show minimum frame counts and make single-channel registration unavailable.
    """
    for name, frames in (("first", 3), ("second", 5)):
        tifffile.imwrite(tmp_path / f"{name}.tif", np.zeros((frames, 8, 8), dtype=np.uint16),
                         imagej=True, metadata={"axes": "TYX"})
    window.adapter.set_runtime_value("unlock_all_tabs", True)
    window._refresh_run_inventory()
    window._refresh_phase_access()
    assert window.file_frames_label.text() == "<u>Frames:</u> ≥ 3"
    toggle = window._editors[StepName.REGISTER_CHANNEL].enable_group
    assert not toggle.isEnabled()
    assert "at least 2 image channels" in toggle.toolTip()
    assert StepName.TRACK not in window._step_input_problems()


def test_missing_user_name_is_a_red_console_error(window: FischMainWindow,
                                                 monkeypatch: pytest.MonkeyPatch,
                                                 ) -> None:
    """
    Keep the required-name safeguard without opening a blocking warning dialog.
    """
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail("Unexpected validation popup"))
    window.user_name_edit.clear()
    window._next_from_convert()
    assert "✖ ERROR | Enter a user name." in window.console.toPlainText()
    assert window.console.textCursor().charFormat().foreground().color().name() == "#e57373"
    assert window._thread is None


def test_quantification_without_processing_warns_and_blocks(window: FischMainWindow,
                                                           monkeypatch: pytest.MonkeyPatch,
                                                           ) -> None:
    """
    Warn on inclusion, block launch, and explain bypass through the common tooltip.
    """
    for step in (StepName.SEGMENT, StepName.TRACK):
        window._editors[step].enable_group.setChecked(False)
    toggle = window._editors[StepName.EXTRACT].enable_group
    toggle.setChecked(True)
    message = "Quantification requires Segmentation or Tracking to be included in the workflow."
    assert window.console.toPlainText().count(message) == 1
    assert "⚠ WARNING | " + message in window.console.toPlainText()
    assert toggle.title() == "Include in workflow"
    assert "bypass this step" in toggle.toolTip()
    assert "Recompute this step" in window._editors[StepName.EXTRACT].widgets["overwrite"].toolTip()
    monkeypatch.setattr(window, "_save_settings", lambda: pytest.fail("Invalid workflow reached saving"))
    window._launch_pipeline(convert_only=False)
    assert "✖ ERROR | " + message in window.console.toPlainText()
    assert window._thread is None
    window._editors[StepName.SEGMENT].enable_group.setChecked(True)
    assert StepName.EXTRACT not in window._enabled_step_input_problems()


def test_reviewed_rebuild_validates_its_effective_included_steps(window: FischMainWindow, tmp_path: Path) -> None:
    """
    Use the reviewed scope when it includes a required producer absent from the GUI draft.
    """
    from fisch.workflows.file_management.rebuild import ProcessingPlan

    for step in (StepName.SEGMENT, StepName.TRACK):
        window._editors[step].enable_group.setChecked(False)
    window._editors[StepName.EXTRACT].enable_group.setChecked(True)
    window._maintenance_plan = ProcessingPlan(tmp_path, "update",
                                              {tmp_path: (str(StepName.SEGMENT), str(StepName.EXTRACT))}, ())
    assert StepName.EXTRACT not in window._enabled_step_input_problems()


def test_channel_registration_guard_follows_export_choices(window: FischMainWindow, tmp_path: Path) -> None:
    """
    Let users disable incompatible saved settings and restore eligibility by exporting all channels.
    """
    tifffile.imwrite(tmp_path / "input.tif", np.zeros((3, 2, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={"axes": "TCYX"})
    window.adapter.set_field_value(StepName.CONVERT, "channel_labels", ["Red", "Green"])
    window.adapter.set_runtime_value("unlock_all_tabs", True)
    window._refresh_run_inventory()
    window._refresh_phase_access()
    toggle = window._editors[StepName.REGISTER_CHANNEL].enable_group
    assert toggle.isEnabled()
    toggle.setChecked(True)
    window.adapter.set_field_value(StepName.CONVERT, "export_channels", ["Red"])
    window._update_run_button_text()
    assert toggle.isEnabled()
    assert StepName.REGISTER_CHANNEL in window._enabled_step_input_problems()
    toggle.setChecked(False)
    assert not toggle.isEnabled()
    window.adapter.set_field_value(StepName.CONVERT, "export_channels", "all")
    window._update_run_button_text()
    assert toggle.isEnabled()


def test_mixed_raw_channel_counts_block_conversion(window: FischMainWindow,
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
    assert hint.text() == ""
    assert hint.isHidden()
    message = window._raw_input_error()
    assert "✖ ERROR | " + message in window.console.toPlainText()
    assert "Place acquisitions with different channel counts in separate run directories." in message
    assert window.console.textCursor().charFormat().foreground().color().name() == "#e57373"
    window._update_run_button_text()
    window._refresh_run_inventory()
    assert window.console.toPlainText().count(message) == 1
    assert not window.run_button.isEnabled()
    assert "Cannot convert" in window.run_button.toolTip()
    assert "input_1.tif: 1 channel" in window.file_status_label.toolTip()
    assert "input_2.tif: 2 channels" in window._file_guidance().details
    assert "#e57373" in window.file_status_label.styleSheet()
    assert not window._channel_label_warning()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail("Unexpected validation popup"))
    monkeypatch.setattr(window, "_save_settings", lambda: pytest.fail("Mixed channel counts reached pipeline setup"))
    window._launch_pipeline(convert_only=True)
    assert "different numbers of channels (1, 2)" in window.console.toPlainText()
    assert "✖ ERROR |" in window.console.toPlainText()
    assert window.console.textCursor().charFormat().foreground().color().name() == "#e57373"
    assert window._thread is None
    (tmp_path / "input_2.tif").unlink()
    window._refresh_run_inventory()
    assert hint.text() == ""
    assert hint.isHidden()
    assert window.run_button.isEnabled()


def test_label_count_warning_is_orange_nonblocking_and_clears_after_edit(window: FischMainWindow,
                                                                        tmp_path: Path,
                                                                        ) -> None:
    """
    Show exact fallback labels in orange without blocking conversion or repeating unchanged warnings.
    """
    tifffile.imwrite(tmp_path / "input.tif", np.zeros((3, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={"axes": "CYX"})
    window._refresh_run_inventory()
    editor = window._editors[StepName.CONVERT]
    field = cast(ConversionChannelsWidget, editor.widgets["channel_labels"])
    field.set_labels(['Red', 'Green'])
    field.value_changed.emit(field.value())
    message = window._channel_label_warning()
    assert "Expected 3 channels, got 2 channel labels" in message
    assert "default names: C1, C2, C3." in message
    assert not window._raw_input_error()
    assert window.run_button.isEnabled()
    assert "#efb366" in editor.expected_channels_label.styleSheet()
    assert message in window._file_guidance().details
    assert window.console.toPlainText().count(message) == 1
    assert window.console.textCursor().charFormat().foreground().color().name() == "#efb366"
    window._update_run_button_text()
    assert window.console.toPlainText().count(message) == 1
    window._append_log("Normal log message")
    assert window.console.textCursor().charFormat().foreground().color().name() != "#efb366"
    field.set_labels(['Red', 'Green', 'Blue'])
    field.value_changed.emit(field.value())
    assert not window._channel_label_warning()
    assert not editor.expected_channels_label.styleSheet()
    assert window.run_button.isEnabled()


def test_duplicate_stems_load_without_popup(window: FischMainWindow,
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


def test_destination_conflict_identifies_input_in_red(window: FischMainWindow, tmp_path: Path) -> None:
    """
    Show a blocking destination conflict and its source file through shared inspection.
    """
    tifffile.imwrite(tmp_path / "sample.tif", np.zeros((8, 8), dtype=np.uint16), metadata={"axes": "YX"})
    (tmp_path / "sample").mkdir()
    window._refresh_run_inventory()
    assert not window.run_button.isEnabled()
    assert "Cannot create acquisition folder: sample" in window.run_button.toolTip()
    assert "sample.tif" in window._file_guidance().details
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
    assert list(tmp_path.rglob("proc_array_raw.tif"))
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
    (tmp_path / "proc_array.tif").touch()
    window._populate_from_adapter()
    # Simulate reopening this prepared run with the current conversion settings.
    window._converted_settings = window._conversion_signature()
    window._back_to_convert()
    field = cast(ConversionChannelsWidget, window._editors[StepName.CONVERT].widgets["channel_labels"])
    field.set_labels(['FarRed'])
    field.value_changed.emit(field.value())
    captured = []

    def convert(**kwargs):
        captured.append(kwargs)
        kwargs["run_progress"].add("experiment", {WorkflowStage.CONVERT})
        kwargs["run_progress"].update("experiment", WorkflowStage.CONVERT, StageStatus.COMPLETED)

    monkeypatch.setattr("fisch.gui.main_window.pipeline_worker.start_pipeline", convert)
    window.run_button.click()
    assert window._worker.force_conversion
    wait_for_run(window)
    assert captured[0]["convert_only"]
    assert captured[0]["force_conversion"]
    assert window.adapter.field_value(StepName.CONVERT, "overwrite") is False
    assert window.workflow_pages.currentIndex() == 1


@pytest.mark.parametrize("outcome", ["failure", "cancel", "no_conversion", "changed_while_running"])
def test_unsuccessful_or_changed_conversion_does_not_advance(window, tmp_path, monkeypatch, outcome):
    (tmp_path / "proc_array.tif").touch()
    window._refresh_phase_access()
    window._converted_settings = window._conversion_signature()
    window._editors[StepName.CONVERT].widgets["overwrite"].setChecked(True)
    failures = []
    monkeypatch.setattr(window, "_pipeline_failed", lambda message, details: failures.append(message))

    def convert(**kwargs):
        if outcome == "failure":
            raise RuntimeError("conversion failed")
        if outcome == "cancel":
            from fisch.workflows.runtime.interactive import PipelineCancelled
            raise PipelineCancelled()
        if outcome == "changed_while_running":
            kwargs["run_progress"].add("experiment", {WorkflowStage.CONVERT})
            kwargs["run_progress"].update("experiment", WorkflowStage.CONVERT, StageStatus.COMPLETED)

    monkeypatch.setattr("fisch.gui.main_window.pipeline_worker.start_pipeline", convert)
    window.run_button.click()
    if outcome == "changed_while_running":
        field = cast(ConversionChannelsWidget, window._editors[StepName.CONVERT].widgets["channel_labels"])
        field.set_labels(['Changed'])
        field.value_changed.emit(field.value())
    wait_for_run(window)
    assert window.workflow_pages.currentIndex() == 0
    assert not window._conversion_is_current()
    assert bool(failures) == (outcome == "failure")


def test_processing_run_uses_normal_pipeline(window, tmp_path, monkeypatch):
    (tmp_path / "proc_array.tif").touch()
    window._refresh_phase_access()
    window._converted_settings = window._conversion_signature()
    window._next_from_convert()
    captured = []
    monkeypatch.setattr("fisch.gui.main_window.pipeline_worker.start_pipeline", lambda **kwargs: captured.append(kwargs))
    window.run_button.click()
    assert not window._worker.convert_only
    assert not window._worker.force_conversion
    wait_for_run(window)
    assert not captured[0]["convert_only"]
    assert not captured[0]["force_conversion"]


def test_selecting_saved_converted_run_opens_processing_with_loaded_settings(window, tmp_path):
    root = tmp_path / "saved_run"
    root.mkdir()
    tifffile.imwrite(root / "input.tif", np.zeros((8, 8), dtype=np.uint16), metadata={"axes": "YX"})
    (root / "proc_array.tif").touch()
    saved = SettingsAdapter()
    saved.run_dir = str(root)
    saved.set_field_value(StepName.CONVERT, "channel_labels", ["FarRed"])
    saved.set_field_value(StepName.CONVERT, "overwrite", True)
    saved.save_to_run_dir()

    window._switch_run_dir(str(root))
    QApplication.processEvents()
    assert "channel labels" not in window.console.toPlainText()
    assert window.workflow_pages.currentIndex() == 1
    assert window._current_step == StepName.REGISTER_TIME
    assert window._conversion_is_current()
    window._back_to_convert()
    window._next_from_convert()
    assert window.workflow_pages.currentIndex() == 1
    assert window._thread is None


def test_empty_channel_labels_use_defaults_without_warning(window: FischMainWindow, tmp_path: Path) -> None:
    tifffile.imwrite(tmp_path / "input.tif", np.zeros((2, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={"axes": "CYX"})
    window.adapter.set_field_value(StepName.CONVERT, "channel_labels", [])
    window._refresh_run_inventory()
    assert not window._channel_label_warning()
    assert "channel labels" not in window.console.toPlainText()


@pytest.fixture(autouse=True)
def isolate_settings_navigation_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Isolate navigation/settings tests from metadata checks on empty image fixtures.
    """
    from fisch.workflows.checks.models import RunCompatibility
    monkeypatch.setattr('fisch.gui.main_window.window.inspect_run_compatibility',
        lambda root: RunCompatibility(Path(root).resolve(), (), (), (), ()))
