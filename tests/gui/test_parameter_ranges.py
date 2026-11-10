"""Check that bounded scores retain decimal editing in the main GUI and tuner."""

import pytest
from PySide6.QtWidgets import QApplication

from fisch.environment.constant import StepName
from fisch.gui.settings import SettingsAdapter, StepSettingsEditor
from fisch.gui.settings.field_widgets import FloatWidget
from fisch.gui.viewer.segmentation.settings_panel import CellposeSettingsPanel
from fisch.settings.models import SegmentChannelSettings


@pytest.mark.parametrize("step, path", [
    (StepName.BG_SUB, "threshold"),
    (StepName.TRACK, "postprocess.shape_similarity"),
])
def test_main_score_controls_use_unit_range(step: StepName, path: str) -> None:
    """
    Keep score controls within their declared zero-to-one range.
    """
    app = QApplication.instance() or QApplication([])
    editor = StepSettingsEditor(SettingsAdapter(), step)
    try:
        widget = editor.widgets[path]
        assert isinstance(widget, FloatWidget)
        assert (widget.minimum(), widget.maximum()) == (0, 1)
        widget.setValue(0.25)
        assert editor.adapter.field_value(step, path) == pytest.approx(0.25)
    finally:
        editor.close()
        app.processEvents()


@pytest.mark.parametrize("initial", [0, 0.0])
def test_integer_stitch_settings_still_allow_fractional_editing(initial: float) -> None:
    """
    Preserve fractional overlap choices when TOML stores the disabled value as an integer.
    """
    app = QApplication.instance() or QApplication([])
    adapter = SettingsAdapter()
    adapter.set_segment_channels([{"channel": "GFP", "user_settings": {"stitch_threshold": initial}}])
    editor = StepSettingsEditor(adapter, StepName.SEGMENT)
    try:
        widget = editor.channel_widgets[0]["user_settings.stitch_threshold"]
        assert isinstance(widget, FloatWidget)
        assert (widget.minimum(), widget.maximum()) == (0, 1)
        widget.setValue(0.25)
        assert adapter.segmentation_settings().channels[0].user_settings["stitch_threshold"] == pytest.approx(0.25)
    finally:
        editor.close()
        app.processEvents()


def test_segtune_uses_the_same_stitch_range_as_the_model() -> None:
    """
    Preserve the strictest valid overlap value when transferring tuner settings.
    """
    app = QApplication.instance() or QApplication([])
    panel = CellposeSettingsPanel()
    try:
        assert (panel.stitch_threshold.minimum(), panel.stitch_threshold.maximum()) == (0, 1)
        panel.stitch_threshold.setValue(1)
        settings = SegmentChannelSettings(channel="GFP", user_settings=panel.user_settings())
        assert settings.user_settings["stitch_threshold"] == 1
    finally:
        panel.close()
        app.processEvents()
