"""Exercise channel choices, their dependencies, and inspection-only navigation."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QGroupBox, QLineEdit
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from fits.environment.constant import StepName
from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.gui.settings.field_widgets import ChannelSelectionWidget, ExportChannelsWidget, FloatWidget, IntWidget
from fits.gui.theme import get_application
from fits.gui.segmentation_models.loader import model_options_loader
from fits.gui.segmentation_models.options import installed_model_options


@pytest.fixture
def channel_window(tmp_path: Path) -> Iterator[FitsMainWindow]:
    """
    Build editable settings with three source channels and no running processing.
    """
    app = get_application()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "Test"
    adapter.set_runtime_value("unlock_all_tabs", True)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP", "RFP", "DAPI"])
    window = FitsMainWindow(adapter)
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _choices(widget: QComboBox) -> list[str]:
    """
    Return the single-selection options in display order.
    """
    return [widget.itemText(index) for index in range(widget.count())]


def test_export_selections_limit_downstream_image_choices(channel_window: FitsMainWindow) -> None:
    """
    Export all by default, then offer only retained image channels downstream.
    """
    window = channel_window
    exports = window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(exports, ExportChannelsWidget)
    assert exports.value() == ["GFP", "RFP", "DAPI"]
    exports.set_channel_selected(1, False)
    assert window.adapter.exported_channel_labels() == ["GFP", "DAPI"]
    fit = window._editors[StepName.REGISTER_TIME].widgets["fit_channel"]
    reference = window._editors[StepName.REGISTER_CHANNEL].widgets["reference_channel"]
    assert isinstance(fit, QComboBox) and isinstance(reference, QComboBox)
    assert _choices(fit) == ["None", "GFP", "DAPI"]
    assert fit.currentText() == "None"
    assert _choices(reference) == ["", "GFP", "DAPI"]
    assert reference.currentText() == ""
    assert window.adapter.field_value(StepName.REGISTER_CHANNEL, "reference_channel") == ""
    segment = window._editors[StepName.SEGMENT].channel_widgets[0]
    target, nucleus = segment["channel"], segment["nuclear_channel"]
    assert isinstance(target, QComboBox) and isinstance(nucleus, QComboBox)
    assert _choices(target) == ["", "GFP", "DAPI"]
    assert _choices(nucleus) == ["None", "GFP", "DAPI"]


def test_tracking_choices_follow_only_segmentation_targets(channel_window: FitsMainWindow) -> None:
    """
    Keep exported-but-unsegmented channels out of tracking choices.
    """
    window = channel_window
    segment = window._editors[StepName.SEGMENT]
    tracking = window._editors[StepName.TRACK].widgets["channel_to_track"]
    assert isinstance(tracking, ChannelSelectionWidget)
    assert tracking.count() == 0
    target = segment.channel_widgets[0]["channel"]
    assert isinstance(target, QComboBox)
    target.setCurrentText("GFP")
    nucleus = segment.channel_widgets[0]["nuclear_channel"]
    assert isinstance(nucleus, QComboBox)
    nucleus.setCurrentText("RFP")
    segment._add_channel(0)
    second = segment.channel_widgets[1]["channel"]
    assert isinstance(second, QComboBox)
    assert second.currentText() == ""
    second_nucleus = segment.channel_widgets[1]["nuclear_channel"]
    assert isinstance(second_nucleus, QComboBox)
    assert second_nucleus.currentText() == "None"
    second.setCurrentText("DAPI")
    assert tracking.value() == ["GFP", "DAPI"]
    assert [tracking.itemText(index) for index in range(tracking.count())] == ["GFP", "DAPI"]


def test_excluded_channels_offer_exclusive_none(channel_window: FitsMainWindow) -> None:
    """
    Allow multiple excluded channels while keeping None mutually exclusive.
    """
    window = channel_window
    excluded = window._editors[StepName.BG_SUB].widgets["exclude_channel"]
    assert isinstance(excluded, ChannelSelectionWidget)
    assert excluded.itemText(0) == "None"
    assert excluded.is_channel_selected(0)
    excluded.set_channel_selected(1, True)
    excluded.set_channel_selected(2, True)
    assert excluded.value() == ["GFP", "RFP"]
    assert not excluded.is_channel_selected(0)
    excluded.set_channel_selected(0, True)
    assert excluded.value() == []
    assert window.adapter.field_value(StepName.BG_SUB, "exclude_channel") == "None"


def test_source_label_changes_refresh_all_channel_choices(channel_window: FitsMainWindow) -> None:
    """
    Keep labels arbitrary and ordered when source names are edited.
    """
    window = channel_window
    source = window._editors[StepName.CONVERT].widgets["channel_labels"]
    assert isinstance(source, QLineEdit)
    source.setText("First label, second label, third label")
    source.editingFinished.emit()
    exports = window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(exports, ExportChannelsWidget)
    assert exports.value() == ["First label", "second label", "third label"]
    fit = window._editors[StepName.REGISTER_TIME].widgets["fit_channel"]
    assert isinstance(fit, QComboBox)
    assert _choices(fit) == ["None", "First label", "second label", "third label"]


def test_saved_export_subset_survives_editor_rebuild(channel_window: FitsMainWindow) -> None:
    """
    Preserve a deliberately deselected source channel when settings rebuild.
    """
    window = channel_window
    exports = window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(exports, ExportChannelsWidget)
    exports.set_channel_selected(1, False)
    window._populate_from_adapter()
    rebuilt = window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(rebuilt, ExportChannelsWidget)
    assert rebuilt.value() == ["GFP", "DAPI"]


def test_empty_export_selection_blocks_conversion(channel_window: FitsMainWindow) -> None:
    """
    Require at least one exported channel instead of silently restoring all.
    """
    window = channel_window
    exports = window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(exports, ExportChannelsWidget)
    exports.clearSelection()
    assert window.adapter.field_value(StepName.CONVERT, "export_channels") == []
    assert not window.run_button.isEnabled()
    assert "Select at least one channel" in window.run_button.toolTip()


def test_diameter_is_integer_and_flow_values_above_one_are_allowed(channel_window: FitsMainWindow) -> None:
    """
    Use an integer size while retaining the squared-error nature of flow thresholds.
    """
    widgets = channel_window._editors[StepName.SEGMENT].channel_widgets[0]
    diameter = widgets["user_settings.diameter"]
    assert isinstance(diameter, IntWidget)
    diameter.setValue(23)
    flow = widgets["user_settings.flow_threshold"]
    assert isinstance(flow, FloatWidget)
    flow.setValue(1.5)
    assert channel_window.adapter.segment_channels()[0]["user_settings"]["diameter"] == 23
    assert channel_window.adapter.segment_channels()[0]["user_settings"]["flow_threshold"] == 1.5


def test_read_only_next_is_navigation_only(channel_window: FitsMainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Inspect both pages without allowing read-only navigation to launch processing.
    """
    window = channel_window
    monkeypatch.setattr(window, "_run_status", SimpleNamespace(outdated=True))

    def unexpected_launch(**kwargs: object) -> None:
        """
        Fail if inspection starts a pipeline.
        """
        pytest.fail("Read-only navigation launched processing.")

    monkeypatch.setattr(window, "_launch_pipeline", unexpected_launch)
    window._refresh_phase_access()
    window._show_step(StepName.REGISTER_TIME)
    assert not window.run_button.isEnabled()
    window._back_to_convert()
    assert window.run_button.text() == "Next"
    assert window.run_button.isEnabled()
    window.run_button.click()
    assert window.workflow_pages.currentIndex() == 1
    assert not window.run_button.isEnabled()


def test_saved_image_channels_supply_choices_without_source_settings() -> None:
    """
    Fall back to image metadata when opening an existing acquisition's settings.
    """
    adapter = SettingsAdapter()
    adapter.saved_image_channels = ["Existing GFP", "Existing RFP"]
    assert adapter.exported_channel_labels() == ["Existing GFP", "Existing RFP"]


def test_segmentation_model_choices_reuse_installed_builtins(channel_window: FitsMainWindow) -> None:
    """
    Offer the same built-in model list as SegTune without initializing model weights.
    """
    loader = model_options_loader()
    loader.start()
    loader.wait()
    get_application().processEvents()
    options = loader.options
    assert options is not None
    assert installed_model_options() is options
    path = "user_settings.model_type" if options.backend == "v3" else "user_settings.pretrained_model"
    model = channel_window._editors[StepName.SEGMENT].channel_widgets[0][path]
    assert isinstance(model, QComboBox)
    assert set(options.built_in_models).issubset(_choices(model))


def test_channel_dropdowns_cannot_introduce_unavailable_labels(channel_window: FitsMainWindow) -> None:
    """
    Keep required choices blank until a listed channel is selected.
    """
    reference = channel_window._editors[StepName.REGISTER_CHANNEL].widgets["reference_channel"]
    assert isinstance(reference, QComboBox)
    assert not reference.isEditable()
    reference.setCurrentText("Unavailable")
    assert reference.currentText() == ""
    reference.setCurrentText("RFP")
    assert reference.currentText() == "RFP"


def test_channel_headings_stand_out_without_bolding_parameters(channel_window: FitsMainWindow) -> None:
    """
    Emphasize channel headings while keeping controls in the normal parameter font.
    """
    editor = channel_window._editors[StepName.SEGMENT]
    group = next(group for group in editor.findChildren(QGroupBox) if group.title() == "Channel 1")
    assert group.font().bold()
    assert group.fontInfo().pixelSize() > editor.fontInfo().pixelSize()
    assert not editor.channel_widgets[0]["user_settings.diameter"].font().bold()


def test_channel_selections_keep_the_existing_toml_schema(channel_window: FitsMainWindow) -> None:
    """
    Save channel subsets and optional choices using the same CLI-compatible values.
    """
    from fits.settings.loader import load_settings, resolve_step_params
    from fits.settings.models import RegisterTimeSettings, SegmentSettings

    window = channel_window
    exports = window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(exports, ExportChannelsWidget)
    exports.set_channel_selected(1, False)
    reference = window._editors[StepName.REGISTER_CHANNEL].widgets["reference_channel"]
    assert isinstance(reference, QComboBox)
    reference.setCurrentText("DAPI")
    channel = window._editors[StepName.SEGMENT].channel_widgets[0]["channel"]
    assert isinstance(channel, QComboBox)
    channel.setCurrentText("GFP")
    path = window._save_settings()
    assert path is not None
    saved = load_settings(path)
    assert saved["convert"]["params"]["export_channels"] == ["GFP", "DAPI"]
    assert saved["register_channel"]["params"]["reference_channel"] == "DAPI"
    assert RegisterTimeSettings.model_validate(saved["register_time"]["params"]).fit_channel is None
    segment = SegmentSettings.model_validate(resolve_step_params("segment", saved["segment"]))
    assert segment.channels[0].channel == "GFP"
    assert segment.channels[0].nuclear_channel is None


def test_dropdown_keeps_open_while_export_checks_update(channel_window: FitsMainWindow) -> None:
    """
    Toggle several popup rows through real mouse events without losing the popup.
    """
    window = channel_window
    app = get_application()
    window.show()
    app.processEvents()
    exports = window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(exports, ExportChannelsWidget)
    exports.showPopup()
    app.processEvents()
    try:
        for index in (1, 0):
            rectangle = exports.view().visualRect(exports.model().index(index, 0))
            QTest.mouseClick(exports.view().viewport(), Qt.MouseButton.LeftButton, pos=rectangle.center())
            app.processEvents()
            assert exports.view().isVisible()
        assert exports.value() == ["DAPI"]
        assert exports.selection_text() == "DAPI"
        assert window.adapter.exported_channel_labels() == ["DAPI"]
        QTest.keyClick(exports.view(), Qt.Key.Key_Escape)
        app.processEvents()
        assert not exports.view().isVisible()
    finally:
        exports.hidePopup()


@pytest.mark.parametrize("hovered_row", [0, 1])
def test_opening_click_cannot_toggle_a_hovered_channel(channel_window: FitsMainWindow, hovered_row: int) -> None:
    """
    Ignore the opening click's release even when it lands on a popup checkbox row.
    """
    app = get_application()
    channel_window.show()
    app.processEvents()
    exports = channel_window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(exports, ExportChannelsWidget)
    original = exports.value()
    QTest.mousePress(exports, Qt.MouseButton.LeftButton)
    app.processEvents()
    try:
        assert exports.view().isVisible()
        position = exports.view().visualRect(exports.model().index(hovered_row, 0)).center()
        QTest.mouseMove(exports.view().viewport(), position)
        QTest.mouseRelease(exports.view().viewport(), Qt.MouseButton.LeftButton, pos=position)
        assert exports.value() == original
        assert exports.view().isVisible()
        QTest.mouseClick(exports.view().viewport(), Qt.MouseButton.LeftButton, pos=position)
        assert exports.value() == [label for index, label in enumerate(original) if index != hovered_row]
        assert exports.view().isVisible()
    finally:
        exports.hidePopup()


def test_popup_keyboard_preserves_exclusive_none(channel_window: FitsMainWindow) -> None:
    """
    Toggle checked entries with Space while retaining the optional None behavior.
    """
    window = channel_window
    app = get_application()
    editor = window._editors[StepName.BG_SUB]
    editor.enable_group.setChecked(True)
    window._show_step(StepName.BG_SUB)
    window.show()
    app.processEvents()
    excluded = editor.widgets["exclude_channel"]
    assert isinstance(excluded, ChannelSelectionWidget)
    excluded.showPopup()
    app.processEvents()
    try:
        excluded.view().setCurrentIndex(excluded.model().index(1, 0))
        QTest.keyClick(excluded.view(), Qt.Key.Key_Space)
        assert excluded.value() == ["GFP"]
        assert excluded.view().isVisible()
        excluded.view().setCurrentIndex(excluded.model().index(0, 0))
        QTest.keyClick(excluded.view(), Qt.Key.Key_Space)
        assert excluded.value() == []
        assert excluded.selection_text() == "None"
        assert excluded.view().isVisible()
    finally:
        excluded.hidePopup()


def test_collapsed_tooltip_retains_full_selection(channel_window: FitsMainWindow) -> None:
    """
    Keep all names and parameter help available when the control is too narrow.
    """
    source = channel_window._editors[StepName.CONVERT].widgets["channel_labels"]
    assert isinstance(source, QLineEdit)
    names = ["A very long GFP label", "Another long RFP label", "A third long DAPI label"]
    source.setText(", ".join(names))
    source.editingFinished.emit()
    exports = channel_window._editors[StepName.CONVERT].widgets["export_channels"]
    assert isinstance(exports, ExportChannelsWidget)
    exports.setFixedWidth(130)
    channel_window.show()
    get_application().processEvents()
    assert exports.value() == names
    assert exports.selection_text() == ", ".join(names)
    assert ", ".join(names) in exports.toolTip()
    assert "Multiple channels" in exports.toolTip()
