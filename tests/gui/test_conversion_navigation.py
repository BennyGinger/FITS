"""Convert/processing navigation uses successful conversion settings only."""

import os
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

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
    main = FitsMainWindow(adapter)
    _APP.processEvents()
    yield main
    if main._worker is not None:
        main._worker.interaction.cancel()
        wait_for_run(main)
    main.close()
    main.deleteLater()
    _APP.processEvents()


def wait_for_run(window):
    deadline = monotonic() + 15
    while window._thread is not None and monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(5)
    assert window._thread is None, "Pipeline worker did not finish"


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
    assert list(tmp_path.rglob("fits_array.tif"))
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
