import os
from pathlib import Path
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from fits.environment.constant import StepName, WORKFLOW_ORDER
from fits.workflows.runtime.progress import (
    RunProgress, StageStatus, WorkflowStage, format_run_report)
from fits.gui.main_window.pipeline_worker import user_error_message
from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter, StepSettingsEditor
from fits.gui.settings.field_widgets import ChannelSelectionWidget, FloatWidget
from fits.workflows.runtime.errors import StepExecutionError


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _nonblocking_warning_dialogs(monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )


def test_main_window_builds_all_steps_and_dynamic_editors(tmp_path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    (tmp_path / "fits_array.tif").touch()
    window = FitsMainWindow(adapter)

    assert window.convert_tabs.count() == 1
    assert window.phase_tabs.count() == 3
    assert window._step_tabs[3].widget(0) is window._editors[StepName.EXTRACT]
    assert not hasattr(window, "step_tree")
    assert set(window._editors) == set(StepName)
    assert window.runtime_editor is not None
    assert window.runtime_editor.widgets["execution"].isEnabled() is False
    assert window.runtime_editor.widgets["log_dir"].value() == ""
    assert window.run_dir_edit.toolTip()
    assert window.browse_button.toolTip()
    assert window.user_name_edit.toolTip()
    for widget in window.runtime_editor.widgets.values():
        assert widget.toolTip()
        form = widget.parentWidget().layout()
        label = form.labelForField(widget)
        assert label.toolTip()

    segment_item = window._editors[StepName.SEGMENT].enable_group
    segment_editor = window._editors[StepName.SEGMENT]
    assert segment_editor.channel_widgets[0]["channel"].isEnabled() is False
    segment_item.setChecked(True)
    window._select_step(StepName.SEGMENT)
    assert adapter.step_enabled(StepName.SEGMENT) is True
    assert window._current_step == StepName.SEGMENT
    assert segment_editor.channel_widgets[0]["channel"].isEnabled() is True

    register_editor = window._editors[StepName.REGISTER_TIME]
    register_editor._update_worker_state()
    assert register_editor.widgets["workers"].isEnabled() is False

    segment_editor.channel_widgets[0]["channel"].setText("GFP")
    segment_editor.sync_to_adapter()
    assert adapter.segment_channels()[0]["channel"] == "GFP"

    window.close()


def test_tracking_channels_follow_segmentation_multi_selection(tmp_path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_segment_channels([{"channel": "BFP"}, {"channel": "GFP"}])
    adapter.set_field_value(StepName.TRACK, "channel_to_track", [])
    window = FitsMainWindow(adapter)
    segment_editor = window._editors[StepName.SEGMENT]
    tracking_editor = window._editors[StepName.TRACK]
    selector = tracking_editor.widgets["channel_to_track"]

    assert isinstance(selector, ChannelSelectionWidget)
    assert selector.value() == ["BFP", "GFP"]
    assert selector.height() < selector.sizeHintForRow(0) * 3

    selector.item(0).setSelected(False)
    assert adapter.field_value(StepName.TRACK, "channel_to_track") == ["GFP"]
    segment_editor.channel_widgets[1]["channel"].setText("RFP")
    segment_editor.channel_widgets[1]["channel"].editingFinished.emit()

    assert [selector.item(index).text() for index in range(selector.count())] == [
        "BFP", "RFP"]
    assert selector.value() == ["RFP"]
    assert adapter.field_value(StepName.TRACK, "channel_to_track") == ["RFP"]
    window.close()


def test_conversion_and_processing_are_distinct_pages(tmp_path) -> None:
    app = _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    app.processEvents()
    assert window.workflow_pages.currentIndex() == 0
    assert window.run_button.text() == "Next"
    assert window.back_button.isHidden()
    assert not window._editors[StepName.SEGMENT].isEnabled()
    assert not window.segtune_button.isEnabled()
    assert [window.phase_tabs.tabText(i) for i in range(3)] == [
        "Preprocess", "Process", "Analysis"]
    assert [window._step_tabs[1].tabText(i) for i in range(3)] == [
        "Frame-shift", "Channel-shift", "Background subtraction"]
    window.close()


def test_reopening_converted_experiment_starts_on_preprocess(tmp_path) -> None:
    _application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    assert window.workflow_pages.currentIndex() == 1
    assert window.phase_tabs.currentIndex() == 0
    assert window._current_step == StepName.REGISTER_TIME
    assert window.run_button.text() == "Run pipeline"
    assert not window.back_button.isHidden()
    window._back_to_convert()
    assert window.workflow_pages.currentIndex() == 0
    assert window.run_button.text() == "Next"
    window._next_from_convert()
    assert window.workflow_pages.currentIndex() == 1
    assert window._thread is None
    window.close()


def test_settings_remain_editable_during_run(tmp_path) -> None:
    app = _application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "test"
    window = FitsMainWindow(adapter)
    app.processEvents()
    saved_path = adapter.save_to_run_dir()
    saved_settings = saved_path.read_bytes()
    window._set_running(True)
    for button in (window.run_button, window.load_button, window.save_button,
                   window.browse_button, window.back_button,
                   window.report_button, window.tracking_viewer_button):
        assert not button.isEnabled()
    assert not window.run_dir_edit.isEnabled()
    assert not window.user_name_edit.isEnabled()
    assert not window.segtune_button.isEnabled()
    assert not window.channel_labels_button.isEnabled()
    window._select_step(StepName.BG_SUB)
    editor = window._editors[StepName.BG_SUB]
    editor.enable_group.setChecked(True)
    editor.widgets["sigma"].setValue(2.5)
    window._refresh_phase_access()
    assert editor.widgets["sigma"].isEnabled()
    assert adapter.field_value(StepName.BG_SUB, "sigma") == 2.5
    assert window.run_button.text() == "Running…"
    assert saved_path.read_bytes() == saved_settings
    window._set_running(False)
    assert window.back_button.isEnabled()
    assert window.segtune_button.isEnabled()
    assert window.run_button.text() == "Run pipeline"
    window.close()


def test_runtime_override_unlocks_settings_but_not_viewers(tmp_path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_runtime_value("unlock_all_tabs", True)
    window = FitsMainWindow(adapter)
    assert window._editors[StepName.BG_SUB].isEnabled()
    assert not window.segtune_button.isEnabled()
    # Debug settings access does not bypass the user-facing Convert page.
    assert window.workflow_pages.currentIndex() == 0
    assert window.run_button.text() == "Next"
    window.close()


def test_runtime_unlock_control_updates_phase_access_immediately(tmp_path) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    assert not window._editors[StepName.BG_SUB].isEnabled()
    window.runtime_editor.widgets["unlock_all_tabs"].setChecked(True)
    assert window._editors[StepName.BG_SUB].isEnabled()
    assert not window.segtune_button.isEnabled()
    window.close()


def test_refresh_keeps_selected_page_when_arrays_already_exist(tmp_path) -> None:
    _application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    window._back_to_convert()
    window._refresh_phase_access()
    assert window.workflow_pages.currentIndex() == 0
    assert window._current_step == StepName.CONVERT
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


def test_tracking_postprocess_controls_follow_toggle() -> None:
    _application()
    adapter = SettingsAdapter()
    editor = StepSettingsEditor(adapter, StepName.TRACK)

    assert editor.widgets["postprocess.enabled"].isChecked() is False
    for path in (
        "postprocess.shape_similarity",
        "postprocess.minimum_appearances",
        "postprocess.extrapolate_start",
        "postprocess.extrapolate_end",
    ):
        assert editor.widgets[path].isEnabled() is False

    editor.widgets["postprocess.enabled"].setChecked(True)
    assert adapter.field_value(StepName.TRACK, "postprocess.enabled") is True
    for path in (
        "postprocess.shape_similarity",
        "postprocess.minimum_appearances",
        "postprocess.extrapolate_start",
        "postprocess.extrapolate_end",
    ):
        assert editor.widgets[path].isEnabled() is True

    editor.close()


def test_sub_unit_float_widget_uses_tenth_steps() -> None:
    _application()

    assert FloatWidget(0.4).singleStep() == pytest.approx(0.1)
    assert FloatWidget(2.0).singleStep() == pytest.approx(1.0)


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


@pytest.mark.parametrize("selection", ["browse", "enter", "drop", "drop_on_field"])
def test_browsing_run_directory_loads_existing_settings(
    tmp_path: Path,
    monkeypatch,
    selection: str,
) -> None:
    app = _application()
    saved_adapter = SettingsAdapter()
    saved_adapter.run_dir = str(tmp_path)
    saved_adapter.user_name = "Saved user"
    saved_adapter.set_step_enabled(StepName.TRACK, True)
    saved_adapter.save_to_run_dir()
    copied_dir = tmp_path / "local_copy"
    (copied_dir / ".fits").mkdir(parents=True)
    shutil.copy2(
        tmp_path / ".fits" / "fits_settings.toml",
        copied_dir / ".fits" / "fits_settings.toml",
    )

    window = FitsMainWindow(SettingsAdapter())
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(copied_dir),
    )

    if selection == "browse":
        window._browse_run_dir()
    elif selection.startswith("drop"):
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(copied_dir))])
        target = window.run_dir_edit if selection == "drop_on_field" else window
        enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime_data,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(target, enter)
        assert enter.isAccepted()
        drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime_data,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(target, drop)
        assert drop.isAccepted()
    else:
        window.run_dir_edit.setText(str(copied_dir))
        window.run_dir_edit.returnPressed.emit()

    assert window.adapter.run_dir == str(copied_dir.resolve())
    assert window.run_dir_edit.text() == str(copied_dir.resolve())
    assert window.run_browser.root_path == copied_dir.resolve()
    assert window.adapter.user_name == "Saved user"
    assert window.adapter.step_enabled(StepName.TRACK) is True
    assert window._editors[StepName.TRACK].enable_group.isChecked()
    saved_path = window.adapter.save_to_run_dir()
    reloaded = SettingsAdapter()
    reloaded.load(saved_path)
    assert reloaded.run_dir == str(copied_dir.resolve())
    window.close()


@pytest.mark.parametrize("payload", ["file", "missing", "remote", "multiple", "text", "running"])
def test_folder_drop_rejects_invalid_payloads_and_active_run(tmp_path, payload) -> None:
    app = _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    folder = tmp_path / "new folder"
    folder.mkdir()
    file = tmp_path / "image.tif"
    file.touch()
    mime_data = QMimeData()
    if payload == "text":
        mime_data.setText(str(folder))
    elif payload == "remote":
        mime_data.setUrls([QUrl("https://example.com/folder")])
    else:
        paths = {"file": [file], "missing": [tmp_path / "missing"],
                 "multiple": [folder, tmp_path], "running": [folder]}[payload]
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    if payload == "running":
        window._set_running(True)
    enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime_data,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(window, enter)
    assert not enter.isAccepted()
    # Revalidate at drop time as well, in case a run started during the drag.
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime_data,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.dropEvent(drop)
    assert not drop.isAccepted()
    assert window.adapter is adapter
    assert window.run_browser.root_path == tmp_path.resolve()
    if payload == "running":
        window._set_running(False)
    window.close()


def test_run_directory_text_switches_on_enter_and_clears_when_empty(
    tmp_path: Path,
) -> None:
    app = _application()
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


def test_loading_run_directory_settings_does_not_emit_navigation_warnings(
    tmp_path: Path, monkeypatch,
) -> None:
    app = _application()
    saved = SettingsAdapter()
    saved.run_dir = str(tmp_path)
    saved.user_name = "User"
    saved.set_field_value(StepName.CONVERT, "channel_labels", ["GFP", "RFP"])
    saved.save_to_run_dir()

    window = FitsMainWindow(SettingsAdapter())
    app.processEvents()
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, message: warnings.append(message))

    window._switch_run_dir(str(tmp_path))
    app.processEvents()

    assert warnings == []
    assert window.adapter.field_value(StepName.CONVERT, "channel_labels") == [
        "GFP", "RFP"
    ]
    window.close()


def test_switching_folders_loads_own_settings_or_fresh_template(tmp_path) -> None:
    app = _application()
    first = tmp_path / "first"
    second = tmp_path / "second"
    empty = tmp_path / "empty"
    for folder in (first, second, empty):
        folder.mkdir()
    for folder, labels, sigma in ((first, ["GFP"], 3.0),
                                  (second, ["RFP", "BFP"], 7.0)):
        saved = SettingsAdapter()
        saved.run_dir = str(folder)
        saved.user_name = folder.name
        saved.set_field_value(StepName.CONVERT, "channel_labels", labels)
        saved.set_field_value(StepName.BG_SUB, "sigma", sigma)
        saved.set_runtime_value("unlock_all_tabs", True)
        path = saved.save_to_run_dir()
        # A copied settings file must not redirect the selected run folder.
        saved.run_dir = "/some/old/folder"
        path.write_text(saved.document.as_string(), encoding="utf-8")

    window = FitsMainWindow(SettingsAdapter())
    for folder, labels, sigma in ((first, ["GFP"], 3.0),
                                  (second, ["RFP", "BFP"], 7.0)):
        window._switch_run_dir(str(folder))
        app.processEvents()
        assert window.adapter.run_dir == str(folder)
        assert window.run_browser.root_path == folder
        assert window.adapter.user_name == folder.name
        assert window.adapter.field_value(StepName.CONVERT, "channel_labels") == labels
        assert window._editors[StepName.BG_SUB].widgets["sigma"].value() == sigma

    window._switch_run_dir(str(empty))
    app.processEvents()
    fresh = FitsMainWindow(SettingsAdapter())
    expected = fresh.adapter
    expected.run_dir = str(empty)
    assert window.adapter.document == expected.document
    assert window.adapter.source_path is None
    assert window.run_dir_edit.text() == str(empty)
    assert window.user_name_edit.text() == expected.user_name
    assert window._editors[StepName.CONVERT].widgets["channel_labels"].value() == []
    assert window._editors[StepName.BG_SUB].widgets["sigma"].value() == (
        expected.field_value(StepName.BG_SUB, "sigma"))
    assert window.workflow_pages.currentIndex() == 0
    assert not window.segtune_button.isEnabled()
    fresh.close()

    window._switch_run_dir(str(first))
    app.processEvents()
    assert window.adapter.field_value(StepName.CONVERT, "channel_labels") == ["GFP"]
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


@pytest.mark.parametrize(
    "step",
    [
        StepName.CONVERT,
        StepName.REGISTER_TIME,
        StepName.REGISTER_CHANNEL,
        StepName.BG_SUB,
        StepName.SEGMENT,
        StepName.TRACK,
        StepName.EXTRACT,
        StepName.DISTANCE_PROFILE,
    ],
)
def test_all_workflow_steps_have_descriptive_tooltips_for_every_field(
    step: StepName,
) -> None:
    _application()
    window = FitsMainWindow(SettingsAdapter())
    editor = window._editors[step]

    for path, widget in editor.widgets.items():
        assert widget.toolTip()
        assert widget.toolTip() != path
        form = widget.parentWidget().layout()
        label = form.labelForField(widget)
        assert label.toolTip()
        assert label.toolTip() != path

    window.close()


def test_distance_profile_mask_tooltips_explain_their_roles() -> None:
    _application()
    window = FitsMainWindow(SettingsAdapter())
    editor = window._editors[StepName.DISTANCE_PROFILE]

    assert "distances are measured" in editor.widgets["expected_ref_masks"].toolTip()
    assert "whole image is analysed" in editor.widgets["draw_roi_mask"].toolTip()
    assert "limits the distance-profile analysis" in editor.widgets[
        "expected_roi_masks"
    ].toolTip()
    window.close()


def test_user_error_message_finds_step_error_inside_executor_wrapper() -> None:
    step_error = StepExecutionError(
        "Step 'track' failed for experiment_3: Unknown channel 'GFP'.")
    step_error.__cause__ = ValueError("Unknown channel 'GFP'.")
    wrapper = RuntimeError("Task failed for item")
    wrapper.__cause__ = step_error

    assert user_error_message(wrapper) == (
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


@pytest.mark.parametrize("tool", ["tracking_viewer_button", "report_button"])
@pytest.mark.parametrize("selected_folder", [False, True])
def test_missing_results_buttons_explain_what_to_do_next(
    tmp_path, monkeypatch, tool, selected_folder,
) -> None:
    _application()
    adapter = SettingsAdapter()
    if selected_folder:
        adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda parent, title, message: messages.append((title, message)))
    try:
        window._refresh_phase_access()
        window._refresh_report_button()
        button = getattr(window, tool)
        assert button.isEnabled()
        button.click()
        assert len(messages) == 1
        title, message = messages[0]
        if selected_folder:
            assert title == ("No tracking file found" if tool == "tracking_viewer_button" else "No report found")
            assert "Next" in message
            assert "Run pipeline" in message
        else:
            assert title == "Choose a run folder"
            assert "Browse" in message
        assert window._tracking_viewer is None
    finally:
        window.close()


def test_main_action_buttons_describe_their_behavior(tmp_path) -> None:
    _application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    try:
        assert window.channel_labels_button.text() == "Edit Channel Labels"
        assert "rename channel labels" in window.channel_labels_button.toolTip()
        assert "trajectories" in window.tracking_viewer_button.toolTip()
        assert "latest run report" in window.report_button.toolTip()
        assert "without running" in window.back_button.toolTip()
        assert "all enabled steps" in window.run_button.toolTip()
        window._back_to_convert()
        assert window.run_button.text() == "Next"
        assert "unchanged" in window.run_button.toolTip()
        # Missing-field guidance supplements the action description.
        assert "channel_labels" in window.run_button.toolTip()
    finally:
        window.close()


def test_full_report_button_uses_latest_report_and_browser_activation(tmp_path, monkeypatch) -> None:
    reports = tmp_path / ".fits" / "reports"
    reports.mkdir(parents=True)
    older = reports / "fits_report_20260911_080000.txt"
    latest = reports / "fits_report_20260911_090000.txt"
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


@pytest.mark.parametrize("status,error,opens_report", [
    (StageStatus.COMPLETED, None, False),
    (StageStatus.SKIPPED, None, False),
    (StageStatus.PARTIAL, None, False),
    (StageStatus.FAILED, "Segmentation failed", True),
    (StageStatus.SKIPPED, "Task failed", True),
])
def test_completion_opens_report_only_for_run_errors(
        tmp_path, monkeypatch, status, error, opens_report) -> None:
    app = _application()
    reports = tmp_path / ".fits" / "reports"
    reports.mkdir(parents=True)
    report = reports / "fits_report_20261008_120000.txt"
    report.write_text("run report", encoding="utf-8")
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    progress = RunProgress()
    progress.add("experiment", WorkflowStage)
    progress.update("experiment", WorkflowStage.PROCESS, status, error=error)
    progress.update("experiment", WorkflowStage.ANALYSIS, StageStatus.SKIPPED)
    window._run_progress = progress
    opened = []
    monkeypatch.setattr(window, "_show_report", opened.append)

    window._pipeline_finished()
    window._thread_finished()

    assert opened == ([report] if opens_report else [])
    assert window.report_button.isEnabled()
    assert ("completed with errors" in window.console.toPlainText()) == opens_report
    if not opens_report:
        window._open_latest_report()
        assert opened == [report]
    window.close()


def test_pipeline_failure_opens_available_run_report(tmp_path, monkeypatch) -> None:
    app = _application()
    reports = tmp_path / ".fits" / "reports"
    reports.mkdir(parents=True)
    report = reports / "fits_report_20261008_120000.txt"
    report.write_text("failed run report", encoding="utf-8")
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    window._run_progress = RunProgress()
    window._run_progress.add("experiment", [WorkflowStage.PROCESS])
    window._run_progress.update(
        "experiment", WorkflowStage.PROCESS, StageStatus.FAILED, error="Failed")
    opened = []
    monkeypatch.setattr(window, "_show_report", opened.append)

    window._pipeline_failed("Failed", "Failure traceback")

    assert opened == [report]
    assert "Failure traceback" in window.console.toPlainText()
    window.close()


def test_advanced_settings_collapse_their_space_and_conveyor_is_default():
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
        assert group.sizeHint().height() > before.height()
        group.setChecked(False)
        app.processEvents()
        assert group.sizeHint() == before
    window.close()


def test_advanced_fields_expand_the_tab_scroll_range() -> None:
    app = _application()
    editor = StepSettingsEditor(SettingsAdapter(), StepName.BG_SUB)
    editor.resize(700, 240)
    editor.show()
    app.processEvents()
    app.processEvents()
    collapsed = editor.scroll_area.verticalScrollBar().maximum()
    editor.show_advanced_settings()
    app.processEvents()
    app.processEvents()
    assert editor.scroll_area.verticalScrollBar().maximum() > collapsed
    editor._advanced_group.setChecked(False)
    app.processEvents()
    app.processEvents()
    assert editor.scroll_area.verticalScrollBar().maximum() == collapsed
    editor.close()


def test_convert_projection_none_can_be_selected() -> None:
    _application()
    adapter = SettingsAdapter()
    window = FitsMainWindow(adapter)
    combo = window._editors[StepName.CONVERT].widgets["z_projection"]
    combo.setCurrentText("None")
    assert adapter.field_value(StepName.CONVERT, "z_projection") == "None"
    assert StepName.CONVERT not in adapter.validate_steps()
    window.close()


@pytest.mark.parametrize("navigation", ["step", "phase"])
@pytest.mark.parametrize("step", [StepName.CONVERT, StepName.SEGMENT])
def test_leaving_enabled_step_warns_when_user_input_is_missing(
    tmp_path: Path, monkeypatch, navigation: str, step: StepName,
) -> None:
    app = _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_runtime_value("unlock_all_tabs", True)
    if step == StepName.SEGMENT:
        adapter.set_field_value(StepName.CONVERT, "channel_labels", ["RFP"])
        adapter.set_step_enabled(step, True)
    window = FitsMainWindow(adapter)
    app.processEvents()
    window._select_step(step)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append((title, message)),
    )

    if navigation == "step":
        target = StepName.TRACK if step == StepName.SEGMENT else StepName.REGISTER_TIME
        window._select_step(target)
    else:
        window.phase_tabs.setCurrentIndex(2) if step == StepName.SEGMENT else window._select_step(StepName.REGISTER_TIME)

    message = ("Segmentation: Choose a target channel for every section."
               if step == StepName.SEGMENT else
               "Convert: Enter at least one channel label (channel_labels).")
    assert warnings == [(
        "Missing required setting",
        message,
    )]
    assert window._current_step == step
    app.processEvents()
    assert window._current_step == step
    assert window.phase_tabs.currentIndex() == (1 if step == StepName.SEGMENT else 0)
    window.close()


def test_leaving_disabled_step_does_not_warn(tmp_path: Path, monkeypatch) -> None:
    app = _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_runtime_value("unlock_all_tabs", True)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    window = FitsMainWindow(adapter)
    app.processEvents()
    window._select_step(StepName.SEGMENT)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, message: warnings.append(message))

    window._select_step(StepName.TRACK)

    assert warnings == []
    window.close()


def test_leaving_phase_checks_other_enabled_steps_in_that_phase(
    tmp_path: Path, monkeypatch,
) -> None:
    app = _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_runtime_value("unlock_all_tabs", True)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    adapter.set_step_enabled(StepName.REGISTER_CHANNEL, True)
    window = FitsMainWindow(adapter)
    app.processEvents()
    window._select_step(StepName.REGISTER_TIME)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, message: warnings.append(message))

    window.phase_tabs.setCurrentIndex(1)

    assert warnings == [
        "Channel-shift: Choose a reference channel (reference_channel)."
    ]
    assert window._current_step == StepName.REGISTER_TIME
    assert window.phase_tabs.currentIndex() == 0
    window.close()


def test_run_warns_for_all_missing_enabled_step_inputs(
    tmp_path: Path, monkeypatch,
) -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "User"
    for step in (StepName.REGISTER_CHANNEL, StepName.SEGMENT, StepName.TRACK):
        adapter.set_step_enabled(step, True)
    window = FitsMainWindow(adapter)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr(
        window,
        "_save_settings",
        lambda: pytest.fail("invalid settings must prevent launch"),
    )

    window._run_pipeline()

    assert len(warnings) == 1
    title, message = warnings[0]
    assert title == "Cannot run FITS"
    assert "Convert: Enter at least one channel label (channel_labels)." in message
    assert "Channel-shift: Choose a reference channel (reference_channel)." in message
    assert "Segmentation: Choose a target channel for every section." in message
    assert "Tracking: Choose at least one channel to track (channel_to_track)." in message
    window.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_save_and_reload_settings_with_unassigned_segmentation_channel(
    tmp_path, monkeypatch, enabled,
) -> None:
    app = _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_step_enabled(StepName.SEGMENT, enabled)
    window = FitsMainWindow(adapter)
    app.processEvents()
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args: pytest.fail(str(args[2])))

    saved = window._save_settings()
    assert saved is not None
    window.adapter.set_segment_channels([{"channel": "RFP"}])
    window._load_settings_path(saved)

    assert window.adapter.segment_channels()[0]["channel"] == ""
    assert window.adapter.step_enabled(StepName.SEGMENT) == enabled
    assert window._editors[StepName.SEGMENT].channel_widgets[0]["channel"].text() == ""
    window.close()


def test_blank_default_segmentation_channel_blocks_run_until_selected(tmp_path) -> None:
    app = _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_runtime_value("unlock_all_tabs", True)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["RFP"])
    window = FitsMainWindow(adapter)
    app.processEvents()
    field = window._editors[StepName.SEGMENT].channel_widgets[0]["channel"]
    assert field.text() == ""
    assert window.run_button.isEnabled()

    window._select_step(StepName.SEGMENT)
    window._editors[StepName.SEGMENT].enable_group.setChecked(True)
    assert not window.run_button.isEnabled()
    assert "Segmentation: Choose a target channel" in window.run_button.toolTip()

    field.setText("RFP")
    field.editingFinished.emit()
    assert adapter.segmentation_settings().channels[0].channel == "RFP"
    assert window.run_button.isEnabled()

    field.clear()
    field.editingFinished.emit()
    assert not window.run_button.isEnabled()
    window._editors[StepName.SEGMENT].enable_group.setChecked(False)
    assert window.run_button.isEnabled()
    window.close()


def test_run_button_tracks_missing_enabled_inputs(tmp_path: Path) -> None:
    app = _application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    window = FitsMainWindow(adapter)
    app.processEvents()

    assert not window.run_button.isEnabled()
    assert "channel_labels" in window.run_button.toolTip()

    channel_labels = window._editors[StepName.CONVERT].widgets["channel_labels"]
    channel_labels.setText("GFP")
    channel_labels.editingFinished.emit()
    assert window.run_button.isEnabled()
    assert "Before continuing:" not in window.run_button.toolTip()

    window.adapter.set_runtime_value("unlock_all_tabs", True)
    window._refresh_phase_access()
    window._select_step(StepName.REGISTER_CHANNEL)
    window._editors[StepName.REGISTER_CHANNEL].enable_group.setChecked(True)
    assert not window.run_button.isEnabled()
    assert "reference_channel" in window.run_button.toolTip()

    reference_channel = window._editors[StepName.REGISTER_CHANNEL].widgets[
        "reference_channel"
    ]
    reference_channel.setText("GFP")
    reference_channel.editingFinished.emit()
    assert window.run_button.isEnabled()
    window.close()


def test_segmentation_tuner_does_not_warn_about_missing_target_channel(
    tmp_path: Path, monkeypatch,
) -> None:
    import fits.gui.viewer.segmentation as segmentation_viewer

    class DummySignal:
        def connect(self, callback) -> None:
            del callback

    class DummyTuner(QWidget):
        def __init__(self, **kwargs) -> None:
            del kwargs
            super().__init__()
            self.settings_applied = DummySignal()

    app = _application()
    (tmp_path / "fits_array.tif").touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    adapter.set_step_enabled(StepName.SEGMENT, True)
    window = FitsMainWindow(adapter)
    app.processEvents()
    window._select_step(StepName.SEGMENT)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, message: warnings.append(message))
    monkeypatch.setattr(segmentation_viewer, "SegmentationTunerWindow", DummyTuner)

    window.segtune_button.click()

    assert warnings == []
    assert isinstance(window._segmentation_tuner, DummyTuner)
    window._segmentation_tuner.close()
    window.close()
