"""Combined tuner behaviour using real TIFFs and no segmentation model execution."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import tifffile
from bioimagequant import CompartmentSettings, compartment_masks
from fits_io import FitsIO
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from fits.environment import constant as cst
from fits.gui.viewer.segmentation.window import SegmentationTunerWindow
from fits.settings.models import ExtractSettings, SegmentChannelSettings, SegmentSettings
from fits.tasks.segmentation.preview_cache import SegmentationPreview
from fits.tasks.segmentation.tuning import SegmentationTuningSession
from fits.gui.viewer.segmentation.worker import PreviewOutcome, PreviewRequest


@pytest.fixture
def image_masks(tmp_path: Path) -> tuple[Path, np.ndarray, np.ndarray]:
    """
    Prepare two image/mask channels with distinct segmentation and edited tracking.
    """
    raw = tmp_path / "input.tif"
    image = np.stack([np.full((16, 16), 100, dtype=np.uint16), np.full((16, 16), 200, dtype=np.uint16)])
    tifffile.imwrite(raw, image, photometric="minisblack", metadata={"axes": "CYX"})
    reader = FitsIO.from_path(raw)
    reader.save_array(image, channel_labels=["Red", "Green"], output_path=tmp_path / cst.FITS_ARRAY_NAME)
    reader = FitsIO.from_path(tmp_path / cst.FITS_ARRAY_NAME)
    segmentation = np.zeros_like(image)
    segmentation[0, 2:9, 2:9] = 3
    segmentation[1, 7:14, 7:14] = 4
    tracking = np.zeros_like(image)
    tracking[0, 1:8, 6:13] = 31
    tracking[1, 8:15, 1:8] = 42
    reader.save_array(segmentation, output_path=tmp_path / cst.FITS_MASK_SEG, artifact_kind=cst.ARTI_SEG)
    reader.save_array(tracking, output_path=tmp_path / cst.FITS_MASK_TRACK_EDITED, artifact_kind=cst.ARTI_TRACK)
    return tmp_path, segmentation, tracking


@pytest.fixture
def tuner(image_masks: tuple[Path, np.ndarray, np.ndarray], monkeypatch: pytest.MonkeyPatch) -> Iterator[SegmentationTunerWindow]:
    """
    Open the compartment tab while retaining normal GUI save/discard behaviour.
    """
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SegmentationTunerWindow, "_initialize_selected_model", lambda self: None)
    monkeypatch.setattr(SegmentationTunerWindow, "_run_preview_when_ready", lambda self: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    parent = QWidget()
    window = SegmentationTunerWindow(image_masks[0], parent=parent, initial_tab="compartment",
                                     segment_settings=SegmentSettings(channels=[SegmentChannelSettings(channel="Red"),
                                                                               SegmentChannelSettings(channel="Green")]),
                                     extract_settings=ExtractSettings(compartments=True, membrane_thickness=1))
    yield window
    window.close()
    parent.close()
    app.processEvents()


def test_saved_mask_priority_and_independent_image_channel(tuner: SegmentationTunerWindow,
                                                         image_masks: tuple[Path, np.ndarray, np.ndarray],
                                                         ) -> None:
    """
    Inspect red-derived tracking rings on green intensity without changing geometry.
    """
    _, segmentation, tracking = image_masks
    tuner.image_viewer.view_box.setRange(xRange=(0, 12), yRange=(0, 12), padding=0)
    assert not tuner.diameter_reference.isVisible()
    entries = [entry.model_copy(deep=True) for entry in tuner._entries]
    expected = compartment_masks(tracking[0], CompartmentSettings(1))["mb"]
    np.testing.assert_array_equal(np.asarray(tuner.image_viewer._mask_array), expected)
    tuner.channel_combo.setCurrentText("Green")
    np.testing.assert_array_equal(np.asarray(tuner.image_viewer._mask_array), expected)
    np.testing.assert_allclose(np.asarray(tuner.image_viewer.image_item.image), 200)
    assert tuner._entries == entries
    tuner.compartment_panel.mask_channels.setCurrentRow(1)
    np.testing.assert_array_equal(np.asarray(tuner.image_viewer._mask_array),
                                  compartment_masks(tracking[1], CompartmentSettings(1))["mb"])
    tuner.tool_tabs.setCurrentIndex(0)
    np.testing.assert_array_equal(np.asarray(tuner.image_viewer._mask_array), segmentation[0])
    assert "Saved mask" in tuner.mode_label.text()


def test_compartment_preview_bypasses_tracking(tuner: SegmentationTunerWindow,
                                              image_masks: tuple[Path, np.ndarray, np.ndarray],
                                              ) -> None:
    """
    Use included segmentation for membrane previews even when edited tracking exists.
    """
    tuner._workflow_config = {cst.StepName.SEGMENT: {"enabled": True}, cst.StepName.TRACK: {"enabled": False}}
    tuner._refresh_mask_channels()
    tuner._display_selection()
    expected = compartment_masks(image_masks[1][0], CompartmentSettings(1))["mb"]
    np.testing.assert_array_equal(np.asarray(tuner.image_viewer._mask_array), expected)
    assert cst.FITS_MASK_SEG in tuner.compartment_panel.source_label.text()


def test_thickness_reuses_geometry_and_dilation_rebuilds_it(tuner: SegmentationTunerWindow) -> None:
    """
    Keep the distance map on thickness/background changes and rebuild on dilation.
    """
    geometry = tuner._mask_previews._geometry
    tuner.compartment_panel.thickness.setValue(2)
    assert tuner._mask_previews._geometry is geometry
    tuner.channel_combo.setCurrentText("Green")
    assert tuner._mask_previews._geometry is geometry
    tuner.compartment_panel.dilation.setValue(1)
    assert tuner._mask_previews._geometry is not geometry


def test_new_segmentation_result_invalidates_geometry_and_marks_changed_settings_stale(
        tuner: SegmentationTunerWindow, tmp_path: Path,
        ) -> None:
    """
    Replace only the displayed mask and associate geometry with its actual revision.
    """
    old_geometry = tuner._mask_previews._geometry
    mask = np.zeros((16, 16), dtype=np.uint16)
    mask[4:12, 4:12] = 99
    settings = tuner._preview_channel_settings()
    session = tuner._segmentation_session
    assert session is not None
    session.set_segment_settings(settings)
    cache = tmp_path / "preview.npz"
    cache.touch()
    preview = SegmentationPreview(mask, "YX", 0, ("Red",), cache, False)
    request = PreviewRequest(0, "Red", 0, dict(settings.user_settings))
    tuner._active_request = request
    tuner._preview_finished(PreviewOutcome(request, preview))
    assert tuner._mask_previews._geometry is not old_geometry
    np.testing.assert_array_equal(np.asarray(tuner.image_viewer._mask_array), compartment_masks(mask, CompartmentSettings(1))["mb"])
    tuner.tool_tabs.setCurrentIndex(0)
    tuner.settings_panel.diameter.setValue(37)
    assert "out of date" in tuner.status_label.text()
    # Previewing never writes over the existing saved segmentation or tracking masks.
    assert FitsIO.from_path(tmp_path / cst.FITS_MASK_SEG).get_array().array.max() == 4


def test_save_tabs_and_close_warning_preserve_unsaved_other_tab(
        tuner: SegmentationTunerWindow, monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    """
    Save each destination independently and allow cancelling a close with pending edits.
    """
    segmentation: list[SegmentSettings] = []
    compartments: list[ExtractSettings] = []
    tuner.settings_applied.connect(segmentation.append)
    tuner.compartment_settings_applied.connect(compartments.append)
    tuner.show()
    tuner.compartment_panel.thickness.setValue(2.5)
    tuner.tool_tabs.setCurrentIndex(0)
    tuner.settings_panel.diameter.setValue(35)
    tuner._apply_settings()
    assert tuner.isVisible() and len(segmentation) == 1
    assert segmentation[0].channels[0].user_settings["diameter"] == 35
    assert tuner._has_unsaved_settings()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert tuner.close() is False
    assert tuner.isVisible()
    tuner.tool_tabs.setCurrentIndex(1)
    tuner._apply_settings()
    assert compartments[0].membrane_thickness == 2.5
    assert not tuner._has_unsaved_settings()
    assert tuner.close() is True


def test_colour_selections_are_per_tab_and_do_not_dirty_processing(tuner: SegmentationTunerWindow) -> None:
    """
    Remember solid/custom colours without changing geometry or processing settings.
    """
    assert not tuner._has_unsaved_settings()
    geometry = tuner._mask_previews._geometry
    tuner.mask_colour.set_selection((8, QColor("#123456")))
    assert tuner.image_viewer._mask_color == (18, 52, 86)
    tuner.tool_tabs.setCurrentIndex(0)
    assert tuner.mask_colour.currentText() == "Palette"
    tuner.mask_colour.setCurrentText("Cyan")
    tuner.tool_tabs.setCurrentIndex(1)
    colour = tuner.mask_colour.colour()
    assert colour is not None and colour.name() == "#123456"
    assert tuner._mask_previews._geometry is geometry
    assert not tuner._has_unsaved_settings()


def test_channel_removal_emits_only_target_and_preserves_pending_values(tuner: SegmentationTunerWindow) -> None:
    """
    Immediately delete one saved entry while keeping another entry's edits pending.
    """
    removed: list[str] = []
    tuner.channel_removed.connect(removed.append)
    tuner.tool_tabs.setCurrentIndex(0)
    tuner._select_entry(1)
    tuner.settings_panel.diameter.setValue(55)
    tuner._remove_entry(0)
    assert removed == ["Red"]
    assert [entry.channel for entry in tuner._saved_entries] == ["Green"]
    assert tuner._saved_entries[0].user_settings.get("diameter") != 55
    assert tuner._has_unsaved_settings()


def test_saved_mask_revision_rebuilds_geometry(tuner: SegmentationTunerWindow, tmp_path: Path) -> None:
    """
    Detect a newly published artifact revision even when mask pixels are unchanged.
    """
    from fits_io.writers.metadata_update import rewrite_metadata
    source = tmp_path / cst.FITS_MASK_TRACK_EDITED
    old_geometry = tuner._mask_previews._geometry
    metadata = FitsIO.from_path(source).reader.metadata.new_revision()
    rewrite_metadata(source, metadata)
    tuner._display_selection()
    assert tuner._mask_previews._geometry is not old_geometry


def test_run_preview_uses_mask_channel_and_keeps_image_background(tuner: SegmentationTunerWindow,
                                                                monkeypatch: pytest.MonkeyPatch,
                                                                ) -> None:
    """
    Submit segmentation for the selected mask, independent of the green image layer.
    """
    submitted: list[tuple[str, dict]] = []
    session = tuner._segmentation_session
    assert isinstance(session, SegmentationTuningSession)
    tuner.channel_combo.setCurrentText("Green")
    settings = tuner._preview_channel_settings()
    assert settings.channel == "Red"
    # Exercise request creation and completion through a synchronous test worker.
    def run_preview(frame: int, channel: str, z: int, user_settings: dict) -> SegmentationPreview:
        """
        Return an existing labelled plane instead of invoking a GPU model.
        """
        submitted.append((channel, user_settings))
        mask = np.zeros((16, 16), dtype=np.uint16)
        mask[3:12, 3:12] = 8
        return SegmentationPreview(mask, "YX", frame, (channel,), Path("/tmp/combined-test-preview.npz"), False)
    monkeypatch.setattr(session, "run_preview", run_preview)
    tuner._run_preview()
    assert not tuner.tool_tabs.tabBar().isEnabled()
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if tuner._thread is None else None)
    timer.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()
    assert tuner._thread is None
    assert submitted[0][0] == "Red"
    assert tuner.channel_combo.currentText() == "Green"
    np.testing.assert_allclose(np.asarray(tuner.image_viewer.image_item.image), 200)
    assert set(np.unique(np.asarray(tuner.image_viewer._mask_array))) == {0, 8}


def test_main_gui_receives_targeted_channel_deletion_and_compartment_settings(
        tuner: SegmentationTunerWindow, image_masks: tuple[Path, np.ndarray, np.ndarray],
        ) -> None:
    """
    Apply each tab to its main-GUI destination without saving unrelated pending edits.
    """
    from fits.gui.main_window import FitsMainWindow
    from fits.gui.settings import SettingsAdapter
    from fits.gui.segmentation_models.loader import model_options_loader
    loader = model_options_loader()
    loader.start()
    loader.wait()
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    app.processEvents()
    adapter = SettingsAdapter()
    adapter.run_dir = str(image_masks[0])
    adapter.set_segment_channels([{"channel": "Red"}, {"channel": "Green", "user_settings": {"diameter": 14}}])
    adapter.set_field_value(cst.StepName.EXTRACT, "additional_properties", ["eccentricity"])
    main = FitsMainWindow(adapter)
    main._open_segmentation_tuner("compartment")
    active = main._segmentation_tuner
    assert isinstance(active, SegmentationTunerWindow)
    try:
        assert active._in_compartment()
        main._editors[cst.StepName.EXTRACT].show_advanced_settings()
        active.compartment_panel.thickness.setValue(3)
        active.compartment_panel.save_masks.setChecked(True)
        active._apply_settings()
        assert main._editors[cst.StepName.EXTRACT].advanced_settings_visible
        assert adapter.field_value(cst.StepName.EXTRACT, "membrane_thickness") == 3
        assert adapter.field_value(cst.StepName.EXTRACT, "save_compartment_masks") is True
        assert adapter.field_value(cst.StepName.EXTRACT, "additional_properties") == ["eccentricity"]
        active.tool_tabs.setCurrentIndex(0)
        active._select_entry(1)
        active.settings_panel.diameter.setValue(55)
        active._remove_entry(0)
        assert [entry["channel"] for entry in adapter.segment_channels()] == ["Green"]
        assert adapter.segment_channels()[0]["user_settings"]["diameter"] == 14
        active._apply_settings()
        assert adapter.segment_channels()[0]["user_settings"]["diameter"] == 55
    finally:
        active.close()
        main.close()


def test_standalone_saves_both_tabs_to_run_settings(
        tuner: SegmentationTunerWindow, image_masks: tuple[Path, np.ndarray, np.ndarray],
        ) -> None:
    """
    Persist standalone changes through the ordinary run-settings path.
    """
    from fits.gui.settings import SettingsAdapter
    from fits.settings.loader import run_settings_path
    root = image_masks[0]
    standalone = SegmentationTunerWindow(root, initial_tab="compartment",
                                         segment_settings=SegmentSettings(channels=[SegmentChannelSettings(channel="Red")]))
    try:
        standalone.compartment_panel.thickness.setValue(2.5)
        standalone.compartment_panel.enabled.setChecked(True)
        standalone.compartment_panel.save_masks.setChecked(True)
        standalone._apply_settings()
        standalone.tool_tabs.setCurrentIndex(0)
        standalone.settings_panel.diameter.setValue(45)
        standalone._apply_settings()
        loaded = SettingsAdapter()
        loaded.load(run_settings_path(root))
        assert loaded.run_dir == str(root)
        assert loaded.field_value(cst.StepName.EXTRACT, "membrane_thickness") == 2.5
        assert loaded.field_value(cst.StepName.EXTRACT, "save_compartment_masks") is True
        assert loaded.segmentation_settings().channels[0].user_settings["diameter"] == 45
        assert not standalone._has_unsaved_settings()
    finally:
        standalone.close()
