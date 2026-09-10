import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fits.environment.constant import StepName
from fits.gui.settings_adapter import SettingsAdapter
from fits.gui.settings_editor import StepSettingsEditor

_APP = None


def test_mask_request_controls_follow_optional_toggles():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    adapter = SettingsAdapter()
    extraction = StepSettingsEditor(adapter, StepName.EXTRACT)
    profile = StepSettingsEditor(adapter, StepName.DISTANCE_PROFILE)
    assert not extraction.widgets['expected_ref_masks'].isEnabled()
    extraction.widgets['draw_ref_mask'].setChecked(True)
    assert extraction.widgets['expected_ref_masks'].isEnabled()
    assert extraction.widgets['expected_ref_masks'].minimum() == 1
    assert 'draw_ref_mask' not in profile.widgets
    assert profile.widgets['expected_ref_masks'].isEnabled()
    assert not profile.widgets['expected_roi_masks'].isEnabled()
    profile.widgets['draw_roi_mask'].setChecked(True)
    assert profile.widgets['expected_roi_masks'].isEnabled()
    profile.widgets['expected_roi_masks'].setValue(0)
    assert adapter.field_value(StepName.DISTANCE_PROFILE, 'expected_roi_masks') == 0
    profile.set_editable(False)
    assert not profile.widgets['expected_ref_masks'].isEnabled()
    assert not profile.widgets['expected_roi_masks'].isEnabled()
    profile.set_editable(True)
    assert profile.widgets['expected_ref_masks'].isEnabled()
    assert profile.widgets['expected_roi_masks'].isEnabled()
    extraction.close()
    profile.close()
