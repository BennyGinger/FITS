"""Applying tuner values should reveal only changed advanced settings."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from fits.environment.constant import StepName
from fits.gui.main_window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.settings.models import BGSubSettings, RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan

_APP = None


@pytest.fixture
def main(tmp_path):
    """Build a settings window without launching any processing workers."""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_segment_channels([{"channel": "GFP"}])
    window = FitsMainWindow(adapter)
    yield window
    window.close()
    window.deleteLater()
    QApplication.processEvents()


@pytest.mark.parametrize("change,expanded", [
    ({}, False), ({"size": 9}, False), ({"sigma": 1.5}, False),
    ({"exclude_channel": ["RFP"]}, False), ({"threshold": 0.25}, True),
    ({"statistic": "mean"}, True),
])
def test_background_reveals_changed_advanced_values_only(main, change, expanded):
    """Basic or unchanged saves stay collapsed; threshold/statistic edits expand."""
    params = dict(main.adapter.as_mapping()["bg_sub"]["params"])
    settings = BGSubSettings.model_validate({**params, **change})
    main._apply_background_settings(settings)
    assert main._editors[StepName.BG_SUB].advanced_settings_visible == expanded


def test_background_unchanged_custom_advanced_values_stay_collapsed(main):
    """Previously customized values do not count as new tuner edits."""
    main.adapter.set_field_value(StepName.BG_SUB, "threshold", 0.25)
    main.adapter.set_field_value(StepName.BG_SUB, "statistic", "mean")
    settings = BGSubSettings.model_validate(main.adapter.as_mapping()["bg_sub"]["params"])
    main._apply_background_settings(settings.model_copy(update={"size": 9}))
    assert not main._editors[StepName.BG_SUB].advanced_settings_visible


@pytest.mark.parametrize("mode", ["time", "channel"])
@pytest.mark.parametrize("change,expanded", [
    ("unchanged", False), ("basic", False), ("preset", False),
    ("manual", True), ("unchanged_manual", False), ("restore_preset", False),
])
def test_registration_uses_effective_values_and_distinguishes_presets(main, mode, change, expanded):
    """Explicit preset values and preset switches do not masquerade as manual changes."""
    step = StepName.REGISTER_TIME if mode == "time" else StepName.REGISTER_CHANNEL
    settings_type = RegisterTimeSettings if mode == "time" else RegisterChannelSettings
    if change in ("unchanged_manual", "restore_preset"):
        main.adapter.set_field_value(step, "backend", "scikit")
        main.adapter.set_field_value(step, "method", "translation")
    params = dict(main.adapter.as_mapping()[step]["params"])
    settings = settings_type.model_validate(params)
    if change == "preset":
        settings = settings.model_copy(update={"context": "complex_drift" if mode == "time" else "channel_shift_complex"})
    if change in ("manual", "unchanged_manual"):
        settings = settings.model_copy(update={"backend": "scikit", "method": "translation"})
    else:
        effective = resolve_registration_plan(settings.context) if change in ("preset", "restore_preset") else resolve_registration_plan(settings.context, settings.backend, settings.method)
        settings = settings.model_copy(update={"backend": effective.backend, "method": effective.method})
    if change == "basic":
        settings = settings.model_copy(update={"reference_strategy": "first"} if mode == "time" else {"reference_frame": 2})
    main._apply_registration_settings(mode, settings)
    assert main._editors[step].advanced_settings_visible == expanded


@pytest.mark.parametrize("kind", ["background", "time", "channel", "segmentation"])
@pytest.mark.parametrize("already_open", [False, True])
def test_tuner_apply_preserves_existing_expanded_sections(main, kind, already_open):
    """All tuners retain user-opened sections, including unrelated workflow steps."""
    step = {"background": StepName.BG_SUB, "time": StepName.REGISTER_TIME,
            "channel": StepName.REGISTER_CHANNEL, "segmentation": StepName.SEGMENT}[kind]
    main._editors[StepName.CONVERT].show_advanced_settings()
    if already_open:
        main._editors[step].show_advanced_settings()
    if kind == "background":
        main._apply_background_settings(BGSubSettings.model_validate(main.adapter.as_mapping()[step]["params"]))
    elif kind in ("time", "channel"):
        settings_type = RegisterTimeSettings if kind == "time" else RegisterChannelSettings
        main._apply_registration_settings(kind, settings_type.model_validate(main.adapter.as_mapping()[step]["params"]))
    else:
        settings = main.adapter.segmentation_settings(for_tuning=True)
        settings.channels[0].user_settings["diameter"] = 25
        main._apply_segmentation_settings(settings)
    assert main._editors[step].advanced_settings_visible == already_open
    assert main._editors[StepName.CONVERT].advanced_settings_visible
