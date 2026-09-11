import os
from pathlib import Path
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from fits.environment.constant import StepName, WORKFLOW_ORDER
from fits.environment.progress import RunProgress, StageStatus, WorkflowStage
from fits.environment.report import format_run_report
from fits.gui.settings_adapter import SettingsAdapter
from fits.gui.window import FitsMainWindow, _user_error_message
from fits.workflows.errors import StepExecutionError


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_builds_all_steps_and_dynamic_editors(tmp_path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    (tmp_path / "fits_array.tif").touch()
    window = FitsMainWindow(adapter)

    assert window.step_tree.topLevelItemCount() == len(WORKFLOW_ORDER)
    assert set(window._editors) == set(StepName)
    assert window.runtime_editor is not None
    assert window.runtime_editor.widgets["execution"].isEnabled() is False
    assert window.runtime_editor.widgets["log_dir"].value() == ""

    segment_item = window._step_items[StepName.SEGMENT]
    segment_editor = window._editors[StepName.SEGMENT]
    assert segment_editor.widgets["channel_to_segment"].isEnabled() is False
    segment_item.setCheckState(0, Qt.CheckState.Checked)
    assert adapter.step_enabled(StepName.SEGMENT) is True
    assert window.settings_stack.currentWidget() is window._editors[StepName.SEGMENT]
    assert segment_editor.widgets["channel_to_segment"].isEnabled() is True

    register_editor = window._editors[StepName.REGISTER_TIME]
    register_editor._update_worker_state()
    assert register_editor.widgets["workers"].isEnabled() is False

    segment_editor.widgets["channel_to_segment"].setText("GFP, RFP")
    segment_editor.sync_to_adapter()
    assert adapter.field_value(StepName.SEGMENT, "channel_to_segment") == ["GFP", "RFP"]

    window.close()


def test_phase_tabs_unlock_when_prepared_image_appears(tmp_path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)

    assert [window.phase_tabs.tabText(i) for i in range(window.phase_tabs.count())] == [
        "Convert ✓", "Preprocess", "Process", "Analysis"]
    assert window.phase_tabs.isTabEnabled(0)
    assert window.run_button.text() == "Convert experiment(s)"
    for phase in range(1, 4):
        assert not window.phase_tabs.isTabEnabled(phase)
    assert window._step_items[StepName.SEGMENT].isDisabled()
    assert not window.segtune_button.isEnabled()
    assert window._step_items[StepName.REGISTER_TIME].isHidden()

    prepared = tmp_path / "experiment" / "fits_array.tif"
    prepared.parent.mkdir()
    prepared.touch()
    window._refresh_phase_access()

    for phase in range(4):
        assert window.phase_tabs.isTabEnabled(phase)
    assert window.phase_tabs.currentIndex() == 0
    assert window.run_button.text() == "Run pipeline"
    assert not window._step_items[StepName.SEGMENT].isDisabled()
    window.step_tree.setCurrentItem(window._step_items[StepName.SEGMENT])
    assert window.phase_tabs.currentIndex() == 2
    assert window.settings_stack.currentWidget() is window._editors[StepName.SEGMENT]
    assert not window._step_items[StepName.SEGMENT].isHidden()
    assert window._step_items[StepName.CONVERT].isHidden()
    window.close()


def test_runtime_override_unlocks_settings_but_not_viewers(tmp_path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_runtime_value("unlock_all_tabs", True)
    adapter.set_step_enabled(StepName.REGISTER_CHANNEL, True)
    window = FitsMainWindow(adapter)

    assert all(window.phase_tabs.isTabEnabled(i) for i in range(4))
    assert window.run_button.text() == "Run pipeline"
    assert window.phase_tabs.tabText(1) == "Preprocess ✓"
    assert not window.segtune_button.isEnabled()

    window.phase_tabs.setCurrentIndex(1)
    visible = {
        step for step, item in window._step_items.items() if not item.isHidden()
    }
    assert visible == {
        StepName.REGISTER_TIME, StepName.REGISTER_CHANNEL, StepName.BG_SUB
    }
    window.close()


def test_runtime_unlock_control_updates_phase_access_immediately(tmp_path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)

    unlock = window.runtime_editor.widgets["unlock_all_tabs"]
    unlock.setChecked(True)

    assert adapter.runtime_value("unlock_all_tabs") is True
    assert all(window.phase_tabs.isTabEnabled(i) for i in range(4))
    assert window.run_button.text() == "Run pipeline"
    assert not window.segtune_button.isEnabled()
    window.close()


def test_refresh_keeps_selected_phase_when_arrays_already_exist(tmp_path) -> None:
    _application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)

    window.phase_tabs.setCurrentIndex(0)
    window._refresh_phase_access()

    assert window.phase_tabs.currentIndex() == 0
    assert window.step_tree.currentItem() is window._step_items[StepName.CONVERT]
    window.close()


def test_custom_runtime_settings_start_collapsed() -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.set_runtime_value("execution", "batch")

    window = FitsMainWindow(adapter)

    assert window.runtime_editor is not None
    assert not window.runtime_editor._advanced_group.isChecked()
    assert window.runtime_editor.widgets["execution"].currentText() == "batch"
    window.close()


def test_custom_log_directory_in_advanced_runtime_settings(tmp_path: Path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.set_runtime_value("log_dir", str(tmp_path))
    window = FitsMainWindow(adapter)
    editor = window.runtime_editor
    assert editor is not None
    assert not editor._advanced_group.isChecked()
    editor._advanced_group.setChecked(True)
    assert editor.widgets["log_dir"].isEnabled()
    editor.widgets["log_dir"].setText("")
    editor.sync_to_adapter()
    assert adapter.runtime_value("log_dir") == ""
    window.close()


@pytest.mark.parametrize("selection", ["browse", "enter"])
def test_browsing_run_directory_loads_existing_settings(
    tmp_path: Path,
    monkeypatch,
    selection: str,
) -> None:
    _application()
    saved_adapter = SettingsAdapter()
    saved_adapter.run_dir = str(tmp_path)
    saved_adapter.user_name = "Saved user"
    saved_adapter.set_step_enabled(StepName.TRACK, True)
    saved_adapter.save_to_run_dir()
    copied_dir = tmp_path / "local_copy"
    copied_dir.mkdir()
    shutil.copy2(tmp_path / "fits_settings.toml", copied_dir / "fits_settings.toml")

    window = FitsMainWindow(SettingsAdapter())
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(copied_dir),
    )

    if selection == "browse":
        window._browse_run_dir()
    else:
        window.run_dir_edit.setText(str(copied_dir))
        window.run_dir_edit.returnPressed.emit()

    assert window.adapter.run_dir == str(copied_dir.resolve())
    assert window.run_dir_edit.text() == str(copied_dir.resolve())
    assert window.run_browser.root_path == copied_dir.resolve()
    assert window.adapter.user_name == "Saved user"
    assert window.adapter.step_enabled(StepName.TRACK) is True
    assert window._step_items[StepName.TRACK].checkState(0) == Qt.CheckState.Checked
    saved_path = window.adapter.save_to_run_dir()
    reloaded = SettingsAdapter()
    reloaded.load(saved_path)
    assert reloaded.run_dir == str(copied_dir.resolve())
    window.close()


def test_run_directory_text_switches_on_enter_and_clears_when_empty(
    tmp_path: Path,
) -> None:
    _application()
    window = FitsMainWindow(SettingsAdapter())

    window.run_dir_edit.setText(str(tmp_path))
    window.run_dir_edit.returnPressed.emit()

    assert window.adapter.run_dir == str(tmp_path.resolve())
    assert window.run_browser.root_path == tmp_path.resolve()

    window.run_dir_edit.clear()

    assert window.adapter.run_dir == ""
    assert window.run_browser.root_path is None
    assert window.run_browser.tree.isHidden() is False
    assert window.run_browser.tree.model() is window.run_browser.empty_model
    window.close()


def test_advanced_fields_start_collapsed_even_when_customized() -> None:
    _application()

    default_window = FitsMainWindow(SettingsAdapter())
    default_convert = default_window._editors[StepName.CONVERT]
    assert default_convert.widgets["compression"].isEnabled() is False
    default_window.close()

    customized = SettingsAdapter()
    customized.set_field_value(StepName.CONVERT, "compression", "lzma")
    custom_window = FitsMainWindow(customized)
    custom_convert = custom_window._editors[StepName.CONVERT]
    assert not custom_convert._advanced_group.isChecked()
    custom_convert._advanced_group.setChecked(True)
    assert custom_convert.widgets["compression"].isEnabled() is True
    custom_window.close()


def test_user_error_message_finds_step_error_inside_executor_wrapper() -> None:
    step_error = StepExecutionError(
        "Step 'track' failed for experiment_3: Unknown channel 'GFP'.")
    step_error.__cause__ = ValueError("Unknown channel 'GFP'.")
    wrapper = RuntimeError("Task failed for item")
    wrapper.__cause__ = step_error

    assert _user_error_message(wrapper) == (
        "Step 'track' failed for experiment_3: Unknown channel 'GFP'.")


def test_completion_report_shows_stage_counts_and_short_failure_path(tmp_path) -> None:
    progress = RunProgress()
    good = (tmp_path / "condition" / "good_s1").as_posix()
    broken = (tmp_path / "condition" / "broken.nd2").as_posix()
    progress.add(good, WorkflowStage)
    progress.add(broken, WorkflowStage)
    for stage in WorkflowStage:
        progress.update(good, stage, StageStatus.COMPLETED)
    progress.update(broken, WorkflowStage.CONVERT, StageStatus.FAILED,
                    error=f"Could not read {broken}")
    progress.skip_pending(broken)

    report = format_run_report(progress, tmp_path)

    assert "Conversion: 1 completed / 0 partial / 0 skipped / 1 failed" in report
    assert "Preprocessing: 1 completed / 0 partial / 1 skipped / 0 failed" in report
    assert "condition/broken.nd2" in report
    assert tmp_path.as_posix() not in report


def test_full_report_button_uses_latest_report_and_browser_activation(tmp_path, monkeypatch) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    older = logs / "fits_report_20260911_080000.txt"
    latest = logs / "fits_report_20260911_090000.txt"
    older.write_text("older", encoding="utf-8")
    latest.write_text("latest", encoding="utf-8")
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    opened = []
    monkeypatch.setattr(window, "_show_report", opened.append)

    assert window.report_button.isEnabled()
    window._open_latest_report()
    window._open_selected_report(older)

    assert opened == [latest, older]
    window.close()


def test_advanced_settings_reserve_space_and_conveyor_is_default():
    app = _application()
    window = FitsMainWindow(SettingsAdapter())
    assert window.adapter.runtime_value("execution") == "conveyor"
    window.show()
    app.processEvents()
    for editor in (window.runtime_editor, window._editors[StepName.CONVERT]):
        group = editor._advanced_group
        before = group.sizeHint()
        group.setChecked(True)
        app.processEvents()
        assert group.sizeHint() == before
        group.setChecked(False)
        app.processEvents()
        assert group.sizeHint() == before
    window.close()
