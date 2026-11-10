"""Compartment controls use the existing FIScH settings editor and persistence."""

from pathlib import Path

from PySide6.QtWidgets import QApplication

from fisch.environment.constant import StepName
from fisch.gui.settings import SettingsAdapter, StepSettingsEditor
from fisch.gui.settings.field_widgets import BoolWidget, FloatWidget


def test_compartment_controls_save_reload_and_validate(tmp_path: Path) -> None:
    """
    Carry edited numerical settings through the GUI, TOML and model validation.
    """
    app = QApplication.instance() or QApplication([])
    adapter = SettingsAdapter()
    adapter.set_step_enabled(StepName.EXTRACT, True)
    editor = StepSettingsEditor(adapter, StepName.EXTRACT)
    try:
        enabled = editor.widgets["compartments"]
        thickness = editor.widgets["membrane_thickness"]
        dilation = editor.widgets["dilation_radius"]
        assert isinstance(enabled, BoolWidget)
        assert isinstance(thickness, FloatWidget)
        assert isinstance(dilation, FloatWidget)
        enabled.setChecked(True)
        thickness.setValue(2.5)
        dilation.setValue(1.5)
        path = adapter.save(tmp_path / "settings.toml")
        restored = SettingsAdapter()
        restored.load(path)
        assert restored.field_value(StepName.EXTRACT, "compartments") is True
        assert restored.field_value(StepName.EXTRACT, "membrane_thickness") == 2.5
        assert restored.field_value(StepName.EXTRACT, "dilation_radius") == 1.5
        assert StepName.EXTRACT not in restored.validate_steps()
        restored.set_field_value(StepName.EXTRACT, "membrane_thickness", 0)
        assert StepName.EXTRACT in restored.validate_steps()
    finally:
        editor.close()
        app.processEvents()
