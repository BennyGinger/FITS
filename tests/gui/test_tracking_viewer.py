from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionGraphicsItem
from skimage.draw import disk

from fits.environment.constant import (
    FITS_ARRAY_NAME,
    FITS_MASK_TRACK,
    FITS_MASK_TRACK_EDITED_FILTERED,
    StepName,
)
from fits.gui.main_window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.gui.viewer.tracking import TrackingViewerSession, TrackingViewerWindow
from fits.gui.viewer.tracking.path_item import TrackPathsItem
from fits.tasks.tracking.mask_prediction import SplitPredictor
from fits.tasks.tracking.mask_prediction.split_geometry import split_mask_automatically
from fits.workflows.runtime.interactive.messages import TrackEditRequest
from fits.workflows.metadata import FitsMeta


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_batched_track_paths_do_not_fill_between_lines() -> None:
    _app()
    item = TrackPathsItem()
    item.set_tracks(
        {
            1: np.asarray([[0, 2, 2]], dtype=float),
            2: np.asarray([[0, 5, 5], [1, 20, 5], [2, 20, 20]], dtype=float),
        },
        color_for=lambda _: QColor("red"),
        thickness=1,
        show_markers=True,
        marker_size=3,
    )
    image = QImage(30, 30, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    item.paint(painter, QStyleOptionGraphicsItem())
    painter.end()

    assert image.pixelColor(15, 10).alpha() == 0


def _editing_session(tracks: np.ndarray) -> TrackingViewerSession:
    session = object.__new__(TrackingViewerSession)
    session.image_session = None
    session._tracks = tracks
    session._axes = "TYX"
    session._channel_labels = ("Channel 1",)
    session._centroid_cache = {}
    session._add_edit_predictor_cache = {}
    session._split_predictor = SplitPredictor()
    session._has_edits = False
    return session


def test_tracking_session_merge_link_and_stop_recalculate_tracks() -> None:
    merge_data = np.zeros((3, 4, 4), dtype=np.uint16)
    merge_data[:, 0, 0] = 10
    merge_data[1:, 0, 1] = 20
    merge = _editing_session(merge_data)
    merge.track_centroids()

    assert merge.merge_tracks((10, 20), 1, 0, 0) == 10
    assert merge.has_edits
    assert merge.tracked_frame(0)[0, 1] == 0
    assert merge.tracked_frame(1)[0, 1] == 10
    np.testing.assert_allclose(merge.track_centroids()[10][1], (1, 0.5, 0))

    link_data = np.zeros((3, 3, 3), dtype=np.uint16)
    link_data[0, 0, 0] = 30
    link_data[2, 2, 2] = 40
    link = _editing_session(link_data)
    assert link.link_tracks((30, 40), 0, 0) == (30, False)
    assert link.tracked_frame(2)[2, 2] == 30

    conflict_data = np.zeros((2, 3, 3), dtype=np.uint16)
    conflict_data[:, 0, 0] = 50
    conflict_data[:, 2, 2] = 60
    conflict = _editing_session(conflict_data)
    assert conflict.link_tracks((50, 60), 0, 0) == (61, True)
    assert set(np.unique(conflict._tracks)) == {0, 61}

    stop_data = np.zeros((3, 3, 3), dtype=np.uint16)
    stop_data[:, 1, 1] = 70
    stop = _editing_session(stop_data)
    assert stop.stop_track(70, 0, 0, 0) == 71
    assert stop.tracked_frame(0)[1, 1] == 70
    assert np.all(stop._tracks[1:, 1, 1] == 71)
    assert merge._operations_used == {"merge"}
    assert link._operations_used == {"link"}
    assert stop._operations_used == {"stop"}


def test_edited_tracking_save_filters_each_channel_and_records_compact_metadata(
    tmp_path: Path,
) -> None:
    tracks = np.zeros((3, 2, 5, 5), dtype=np.uint16)
    tracks[:, 0, 1, 1] = 1
    tracks[0, 0, 2, 2] = 2
    tracks[0, 1, 3, 3] = 9
    session = object.__new__(TrackingViewerSession)
    session.source_path = tmp_path / FITS_MASK_TRACK
    session._tracks = tracks
    session._axes = "TCYX"
    session._channel_labels = ("Blue mask", "Red mask")
    session._centroid_cache = {}
    session._operations_used = {"delete", "add"}
    session._edited_mask_channels = {0}
    session._prediction_channels = [
        {"mask_channel": "Blue mask", "image_channel": "iRed"},
        {"mask_channel": "Blue mask", "image_channel": "iRed"},
    ]
    saved = {}

    class Payload:
        def __init__(self, custom_metadata):
            self.custom_metadata = custom_metadata
            self.axes = None

        def with_fitsio(self, *, axes):
            self.axes = axes
            return self

    session._reader = SimpleNamespace(
        build_payload=lambda **kwargs: Payload(kwargs["custom_metadata"]),
        save_array=lambda array, **kwargs: (
            saved.update(array=array.copy(), kwargs=kwargs) or kwargs["output_path"]),
    )

    pipeline_metadata = FitsMeta.init(user_name="Ben").with_step(
        step_name=StepName.SEGMENT,
        created_by="cellpose-kit",
        exported_channel=[0],
        params={"channel": "Blue mask", "diameter": 30},
    ).to_dict()
    path, metadata = session.save_edited_tracking(
        filter_spec={"operator": "ge", "value": 2},
        filter_condition={"expression": "track_length_frames >= 2"},
        pipeline_metadata=pipeline_metadata,
    )

    assert path == tmp_path / FITS_MASK_TRACK_EDITED_FILTERED
    assert set(np.unique(saved["array"])) == {0, 1}
    assert saved["kwargs"]["metadata"].axes == "TCYX"
    assert metadata["mask_channels"] == ["Blue mask", "Red mask"]
    assert metadata["operations_used"] == ["add", "delete"]
    assert metadata["prediction_image_channels"] == [{
        "mask_channel": "Blue mask", "image_channel": "iRed"}]
    assert metadata["filter_condition"]["expression"] == "track_length_frames >= 2"
    assert metadata["timestamp"]
    assert metadata["fits_version"]
    custom = saved["kwargs"]["metadata"].custom_metadata
    assert custom["pipeline_meta"]["user_name"] == "Ben"
    assert custom["steps"][StepName.SEGMENT]["channels"]["0"]["channel"] == 0
    assert custom["steps"][StepName.SEGMENT]["channels"]["0"][
        "channel_label"] == "Blue mask"
    assert custom["steps"][StepName.EDIT_TRACK]["params"][
        "operations_used"] == ["add", "delete"]
    assert "tracking_edit" not in custom


def test_automatic_split_detects_neck_and_has_balanced_fallback() -> None:
    snowman = np.zeros((60, 60), dtype=bool)
    rows, columns = disk((38, 30), 14, shape=snowman.shape)
    snowman[rows, columns] = True
    rows, columns = disk((16, 30), 9, shape=snowman.shape)
    snowman[rows, columns] = True
    snowman[24:27, 27:34] = True

    proposal = split_mask_automatically(snowman)

    assert proposal.method == "detected_neck"
    assert proposal.regions[16, 30] != proposal.regions[38, 30]

    rectangle = np.zeros((30, 50), dtype=bool)
    rectangle[5:25, 5:45] = True
    fallback = split_mask_automatically(rectangle)
    sizes = [np.count_nonzero(fallback.regions == value) for value in (1, 2)]
    assert fallback.method == "balanced_watershed"
    assert abs(sizes[0] - sizes[1]) <= np.count_nonzero(rectangle) * 0.3


def test_split_preview_does_not_edit_until_applied_and_preserves_old_region() -> None:
    tracks = np.zeros((2, 60, 60), dtype=np.uint16)
    rows, columns = disk((38, 30), 8, shape=tracks.shape[1:])
    tracks[0, rows, columns] = 9
    snowman = np.zeros((60, 60), dtype=bool)
    rows, columns = disk((38, 30), 14, shape=snowman.shape)
    snowman[rows, columns] = True
    rows, columns = disk((16, 30), 9, shape=snowman.shape)
    snowman[rows, columns] = True
    snowman[24:27, 27:34] = True
    tracks[1, snowman] = 9
    session = _editing_session(tracks)

    preview = session.preview_split(9, 1, 0, 0)

    assert not session.has_edits
    assert set(np.unique(session.split_preview_labels(preview))) == {0, 9, 10}
    assert np.all(session.tracked_frame(1)[snowman] == 9)
    assert session.apply_split(preview) == 10
    assert session.has_edits
    assert session.tracked_frame(1)[38, 30] == 9
    assert session.tracked_frame(1)[16, 30] == 10


def test_local_segmentation_adds_and_deletes_one_frame_with_auxiliary_support() -> None:
    images = np.zeros((3, 2, 64, 64), dtype=np.float32)
    tracks = np.zeros((3, 2, 64, 64), dtype=np.uint16)
    centers = ((24, 24), (27, 27), (30, 30))
    for frame, center in enumerate(centers):
        rows, columns = disk(center, 8, shape=tracks.shape[-2:])
        images[frame, 0, rows, columns] = 1.0
        tracks[frame, 1, rows, columns] = 40
        if frame != 1:
            tracks[frame, 0, rows, columns] = 9
    session = object.__new__(TrackingViewerSession)
    session._tracks = tracks
    session._axes = "TCYX"
    session._channel_labels = ("Blue mask", "Red mask")
    session._centroid_cache = {}
    session._add_edit_predictor_cache = {}
    session._has_edits = False
    session.image_session = SimpleNamespace(
        channel_labels=("Blue image", "Red image"),
        display_frame=lambda frame, channel, z: images[
            frame, ("Blue image", "Red image").index(channel)],
    )

    preview = session.preview_add_edit(
        9, 1, "Blue image", "Blue mask", 0, [(27, 27)], [], 24)

    assert preview["auxiliary_weight"] > 0.7
    assert preview["temporal_weight"] == 0.9
    assert session.tracked_frame(1, "Blue mask")[27, 27] == 0
    session.apply_add_edit(preview)
    assert session.tracked_frame(1, "Blue mask")[27, 27] == 9
    session.delete_mask(9, 1, "Blue mask", 0)
    assert session.tracked_frame(1, "Blue mask")[27, 27] == 0
    assert session.has_edits


def test_local_segmentation_can_replace_an_existing_mask() -> None:
    tracks = np.zeros((1, 12, 12), dtype=np.uint16)
    tracks[0, 1:4, 1:4] = 7
    session = _editing_session(tracks)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    replacement = np.zeros((12, 12), dtype=bool)
    replacement[6:10, 7:11] = True

    session.apply_add_edit({
        "track_id": 7,
        "frame_index": 0,
        "mask_channel": 0,
        "image_channel": 0,
        "z_index": 0,
        "bounds": (0, 12, 0, 12),
        "mask": replacement,
        "replace_existing": True,
    })

    assert not np.any(session.tracked_frame(0)[1:4, 1:4])
    assert np.all(session.tracked_frame(0)[6:10, 7:11] == 7)
    assert session._operations_used == {"edit"}


def test_tracking_viewer_loads_tracks_and_optional_raw_image(
    tmp_path: Path, monkeypatch,
) -> None:
    _app()
    image_path = tmp_path / FITS_ARRAY_NAME
    track_path = tmp_path / FITS_MASK_TRACK
    image_path.touch()
    track_path.touch()
    image = np.arange(2 * 2 * 8 * 8, dtype=np.uint16).reshape(2, 2, 8, 8)
    tracks = np.zeros((2, 2, 8, 8), dtype=np.uint16)
    tracks[:, 0, 2:5, 3:6] = 7
    tracks[:, 1, 1:3, 1:3] = 11
    saves = []
    class Payload:
        def __init__(self, custom_metadata):
            self.custom_metadata = custom_metadata
            self.axes = None
        def with_fitsio(self, *, axes):
            self.axes = axes
            return self
    def save_tracking(array, **kwargs):
        saves.append((array, kwargs))
        return kwargs["output_path"]
    def build_payload(**kwargs):
        return Payload(kwargs["custom_metadata"])
    readers = {
        image_path: SimpleNamespace(
            channel_labels=("GFP", "DAPI"),
            get_array=lambda: SimpleNamespace(array=image, axes="TCYX")),
        track_path: SimpleNamespace(
            channel_labels=("GFP", "RFP"),
            get_array=lambda: SimpleNamespace(array=tracks, axes="TCYX"),
            build_payload=build_payload,
            save_array=save_tracking),
    }
    monkeypatch.setattr(
        "fits.interaction.image.FitsIO.from_path", lambda path: readers[Path(path)])
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.FitsIO.from_path",
        lambda path: readers[Path(path)])

    empty_session = TrackingViewerSession(image_path)
    assert empty_session.started_from_image
    assert empty_session.axes == "TCYX"
    assert empty_session.track_channel_labels == ("GFP", "DAPI")
    assert not np.any(empty_session._tracks)
    assert empty_session.next_track_id() == 1

    window = TrackingViewerWindow(tracking_path=track_path)

    assert window._source_path == track_path
    assert window.frame_slider.maximum() == 1
    assert window.overlay_label.text() == "Mask overlay"
    assert window.raw_image_toggle.text() == "Display raw image"
    assert window.channel_combo.currentText() == "GFP"
    assert window.mask_channel_combo.currentText() == "GFP"
    assert window.preview_split_button.text() == "Split mode"
    assert window.add_mask_button.text() == "Add / edit masks mode"
    assert window.add_mask_button.isEnabled()
    assert window.path_color_button.text() == "Center Color"
    assert window.path_color_button.isHidden()
    window.path_color_mode.setCurrentIndex(
        window.path_color_mode.findData("single"))
    assert not window.path_color_button.isHidden()
    assert window.path_color_button.isEnabled()
    window.path_color_mode.setCurrentIndex(
        window.path_color_mode.findData("track"))
    assert window.path_color_button.isHidden()
    assert "color: black" in window.mask_edit_colors_button.styleSheet()
    assert window.local_cell_diameter.parent() is window.image_viewer.canvas
    assert window.diameter_reference.rect().width() == 40
    window.local_cell_diameter.setValue(32)
    assert window.diameter_reference.rect().width() == 32
    assert window.image_viewer.mask_item.image[3, 4, 3] == 255
    assert window._track_at_position(4, 3) == 7
    window.show_track_paths.setChecked(False)
    assert window._track_at_position(4, 3) == 7
    window.show_track_paths.setChecked(True)
    window._toggle_track_selection(7)
    assert window.track_selection_label.text() == "Selected tracks: 7"
    assert window.stop_track_button.isEnabled()
    assert not window.merge_tracks_button.isEnabled()
    window._toggle_track_selection(8)
    assert window.merge_tracks_button.isEnabled()
    assert window.link_tracks_button.isEnabled()
    assert not window.stop_track_button.isEnabled()
    window._clear_track_selection()
    assert window.add_mask_button.isEnabled()
    window.add_mask_button.setChecked(True)
    clipped = window._clip_local_mask(np.ones((8, 8), dtype=bool))
    assert not np.any(clipped[2:5, 3:6])
    window._switch_local_edit_target(7)
    assert window._selected_track_ids == [7]
    assert np.all(window.image_viewer.drawing_mask[2:5, 3:6])
    window._switch_local_edit_target(7)
    assert window._selected_track_ids == []
    window.add_mask_button.setChecked(False)
    window.preview_split_button.setChecked(True)
    window._switch_split_target(7)
    assert window._selected_track_ids == [7]
    assert (window.image_viewer.drawing_item.acceptedMouseButtons()
            != Qt.MouseButton.NoButton)
    assert np.all(window.image_viewer.drawing_mask[2:5, 3:6])
    window._switch_split_target(7)
    assert window._selected_track_ids == []
    window.preview_split_button.setChecked(False)
    assert window.show_track_paths.isChecked()
    assert window.centroid_size.value() == 5
    window.show_centroids.setChecked(False)
    assert not window.centroid_size.isEnabled()
    window.show_centroids.setChecked(True)
    assert window.centroid_size.isEnabled()
    assert len(window._track_path_items) == 1
    centroids = window._tracking_session.track_centroids("GFP", 0)
    assert window._tracking_session.track_centroids("GFP", 0) is centroids
    np.testing.assert_allclose(centroids[7][0], (0, 4, 3))
    session = window._tracking_session
    assert session.track_ids_matching("GFP", 0, "lt", 3) == {7}
    assert session.track_ids_matching("GFP", 0, "le", 2) == {7}
    assert session.track_ids_matching("GFP", 0, "eq", 2) == {7}
    assert session.track_ids_matching("GFP", 0, "ne", 2) == set()
    assert session.track_ids_matching("GFP", 0, "ge", 2) == {7}
    assert session.track_ids_matching("GFP", 0, "gt", 2) == set()
    assert session.track_ids_matching("GFP", 0, "between", 1, 2) == {7}
    x_values, _ = window._track_path_items[0].getData()
    assert len(x_values) == 1
    window.frame_slider.setValue(1)
    x_values, _ = window._track_path_items[0].getData()
    assert len(x_values) == 2
    assert not hasattr(window, "save_display_button")
    window.channel_combo.setCurrentText("DAPI")
    window.mask_channel_combo.setCurrentText("RFP")
    assert window.channel_combo.currentText() == "DAPI"
    assert window.mask_channel_combo.currentText() == "RFP"
    assert window.image_viewer.mask_item.image[1, 1, 3] == 255
    assert len(window._track_path_items) == 1
    window.raw_image_toggle.setChecked(False)
    assert not window.image_viewer.image_item.isVisible()
    assert window.image_viewer.mask_item.isVisible()
    window.raw_image_toggle.setChecked(True)
    assert not window.filter_operator.isEnabled()
    window.filter_tracks.setChecked(True)
    assert window.filter_operator.isEnabled()
    window.filter_operator.setCurrentIndex(window.filter_operator.findData("gt"))
    window.filter_value.setValue(2)
    assert not np.any(window.image_viewer.mask_item.image[..., 3])
    assert window._track_path_items[0].getData()[0].size == 0
    window.filter_operator.setCurrentIndex(window.filter_operator.findData("ge"))
    assert np.any(window.image_viewer.mask_item.image[..., 3])
    window.close()

    empty_window = TrackingViewerWindow(tracking_path=image_path)
    assert empty_window._tracking_session.started_from_image
    assert empty_window.add_mask_button.isEnabled()
    assert empty_window.track_selection_label.text() == "Selected tracks: none"
    empty_window.add_mask_button.setChecked(True)
    assert empty_window._collect_local_prompts
    assert empty_window._local_target_track_id == 1
    manual_mask = np.zeros((8, 8), dtype=np.uint8)
    manual_mask[2:5, 3:6] = 1
    empty_window.image_viewer._last_drawing_selection = manual_mask.astype(bool)
    empty_window.image_viewer._last_drawing_was_click = False
    empty_window.image_viewer._drawing_operation = "add"
    empty_window._local_drawing_finished(manual_mask)
    assert empty_window.accept_mask_button.isEnabled()
    empty_window.accept_mask_button.click()
    assert np.all(empty_window._tracking_session.tracked_frame(0, 0)[2:5, 3:6] == 1)
    assert empty_window.frame_slider.value() == 1
    assert empty_window._selected_track_ids == [1]
    assert empty_window.add_mask_button.isChecked()
    assert empty_window._collect_local_prompts
    empty_window.add_mask_button.setChecked(False)
    assert not empty_window._collect_local_prompts
    empty_window.close()

    view_only_window = TrackingViewerWindow(
        tracking_path=track_path, editing_enabled=False)
    assert view_only_window.windowTitle() == "FITS Tracking Viewer"
    assert view_only_window.track_edit_section.isHidden()
    assert view_only_window.mask_edit_section.isHidden()
    assert view_only_window.local_cell_diameter.isHidden()
    assert view_only_window.file_filters == (FITS_MASK_TRACK,)
    assert view_only_window.display_label_edit.placeholderText() == "Optional"
    assert view_only_window.save_display_button.text() == "Save current display"
    assert view_only_window.save_display_button.isEnabled()
    view_only_window.close()

    request = TrackEditRequest(
        experiment_id="experiment",
        tracking_path=track_path,
        image_path=image_path,
    )
    pipeline_window = TrackingViewerWindow(
        tracking_path=track_path, pipeline_request=request)
    assert pipeline_window.save_tracking_button.text() == "Save edited tracking"
    assert pipeline_window.save_tracking_button.isEnabled()
    assert pipeline_window.use_original_button.text() == "Use original tracking"
    pipeline_window._pipeline_resolved = True
    pipeline_window.close()


def test_main_window_tracking_button_and_double_click_launch(
    tmp_path: Path, monkeypatch,
) -> None:
    _app()
    track_path = tmp_path / "experiment" / FITS_MASK_TRACK
    track_path.parent.mkdir()
    track_path.touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    window = FitsMainWindow(adapter)
    launched: list[Path] = []
    monkeypatch.setattr(window, "_open_tracking_viewer", launched.append)

    assert window.tracking_viewer_button.isEnabled()
    window._open_selected_report(track_path)
    assert launched == [track_path]
    window.close()
