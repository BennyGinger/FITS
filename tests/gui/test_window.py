import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from fits.environment.constant import StepName
from fits.gui.settings_adapter import SettingsAdapter
from fits.gui.window import FitsMainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_builds_all_steps_and_dynamic_editors() -> None:
    _application()
    adapter = SettingsAdapter()
    window = FitsMainWindow(adapter)

    assert window.step_tree.topLevelItemCount() == 8
    assert set(window._editors) == set(StepName)
    assert window.runtime_editor is not None
    assert window.runtime_editor.widgets["execution"].isEnabled() is False

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


def test_custom_runtime_settings_open_advanced_section() -> None:
    _application()
    adapter = SettingsAdapter()
    adapter.set_runtime_value("execution", "conveyor")

    window = FitsMainWindow(adapter)

    assert window.runtime_editor is not None
    assert window.runtime_editor.widgets["execution"].isEnabled() is True
    window.close()


def test_browsing_run_directory_loads_existing_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _application()
    saved_adapter = SettingsAdapter()
    saved_adapter.run_dir = str(tmp_path)
    saved_adapter.user_name = "Saved user"
    saved_adapter.set_step_enabled(StepName.TRACK, True)
    saved_adapter.save_to_run_dir()

    window = FitsMainWindow(SettingsAdapter())
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(tmp_path),
    )

    window._browse_run_dir()

    assert window.adapter.user_name == "Saved user"
    assert window.adapter.step_enabled(StepName.TRACK) is True
    assert window._step_items[StepName.TRACK].checkState(0) == Qt.CheckState.Checked
    window.close()


def test_advanced_fields_start_disabled_at_defaults_and_open_when_customized() -> None:
    _application()

    default_window = FitsMainWindow(SettingsAdapter())
    default_convert = default_window._editors[StepName.CONVERT]
    assert default_convert.widgets["compression"].isEnabled() is False
    default_window.close()

    customized = SettingsAdapter()
    customized.set_field_value(StepName.CONVERT, "compression", "lzma")
    custom_window = FitsMainWindow(customized)
    custom_convert = custom_window._editors[StepName.CONVERT]
    assert custom_convert.widgets["compression"].isEnabled() is True
    custom_window.close()
