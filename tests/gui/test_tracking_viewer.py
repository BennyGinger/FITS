from __future__ import annotations

import os
from time import monotonic
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
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
from fits.tasks.segmentation.local_seg import SplitPredictor
from fits.workflows.runtime.interactive.messages import TrackEditRequest
from fits.workflows.metadata import FitsMeta


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_trajectories(window: TrackingViewerWindow) -> None:
    deadline = monotonic() + 5
    while (window._trajectory_thread is not None
           or window._trajectory_ready_key != window._trajectory_key()):
        QApplication.processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, window.status_label.text()


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
    assert set(np.unique(conflict_data)) == {0, 61}

    stop_data = np.zeros((3, 3, 3), dtype=np.uint16)
    stop_data[:, 1, 1] = 70
    stop = _editing_session(stop_data)
    assert stop.stop_track(70, 0, 0, 0) == 71
    assert stop.tracked_frame(0)[1, 1] == 70
    assert np.all(stop_data[1:, 1, 1] == 71)

    unlink_data = np.zeros((3, 8, 8), dtype=np.uint16)
    unlink_data[:, 1:3, 1:3] = 80
    unlink_data[1, 5:7, 5:7] = 80
    unlink = _editing_session(unlink_data)
    geometry = unlink_data != 0
    assigned = unlink.unlink_track(80, 0, 0)
    assert len(assigned) == 4
    assert len(set(assigned)) == 4
    assert np.array_equal(unlink_data != 0, geometry)
    assert unlink.undo_last_edit() == 0
    assert np.all(unlink_data[geometry] == 80)
    assert merge._operations_used == {"merge"}
    assert link._operations_used == {"link"}
    assert stop._operations_used == {"stop"}


def test_delete_track_removes_all_masks_and_is_undoable() -> None:
    tracks = np.zeros((4, 8, 8), dtype=np.uint16)
    tracks[0, 1:3, 1:3] = 7
    tracks[2, 3:5, 3:5] = 7
    tracks[1, 5:7, 5:7] = 9
    session = _editing_session(tracks)

    session.delete_track(7, 0, 0)

    assert not np.any(tracks == 7)
    assert np.any(tracks == 9)
    assert session.undo_last_edit() == 0
    assert np.count_nonzero(tracks == 7) == 8

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


def test_split_predictor_uses_mask_geometry_as_prediction_evidence() -> None:
    snowman = np.zeros((60, 60), dtype=bool)
    rows, columns = disk((38, 30), 14, shape=snowman.shape)
    snowman[rows, columns] = True
    rows, columns = disk((16, 30), 9, shape=snowman.shape)
    snowman[rows, columns] = True
    snowman[24:27, 27:34] = True

    proposal = SplitPredictor().predict(snowman)

    assert proposal.regions[16, 30] != proposal.regions[38, 30]

    rectangle = np.zeros((30, 50), dtype=bool)
    rectangle[5:25, 5:45] = True
    rectangle_proposal = SplitPredictor().predict(rectangle)
    sizes = [np.count_nonzero(rectangle_proposal.regions == value)
             for value in (1, 2)]
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
    assert session.undo_last_edit() == 1
    assert np.all(session.tracked_frame(1)[snowman] == 9)
    assert not session.has_edits


def test_microsam_new_mask_does_not_use_the_rendered_click_as_mask_prompt() -> None:
    labels = np.zeros((20, 20), dtype=np.uint16)
    image = np.zeros((20, 20), dtype=np.float32)
    click_drawing = np.zeros((20, 20), dtype=bool)
    click_drawing[10, 10] = True
    captured = {}
    synchronized = []
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0

    def fake_predict(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            mask=np.ones((20, 20), dtype=bool), bounds=(0, 20, 0, 20))

    session._add_edit_backend = SimpleNamespace(
        predict=fake_predict,
        synchronize_mask=lambda mask, context: synchronized.append(
            (mask.copy(), context)) or True,
    )

    session.preview_add_edit(
        7, 0, 0, 0, 0, [(10, 10)], [], 12,
        initial_mask=click_drawing)

    assert captured["initial_mask"] is None
    assert synchronized[0][1] == (7, 0, 0, 0)


def test_opencv_registration_translates_previous_mask_to_current_cell() -> None:
    from fits.gui.viewer.tracking.session import _register_mask_translation

    previous = np.zeros((80, 80), dtype=np.float32)
    previous[25:39, 28:45] = 1.0
    current = np.zeros_like(previous)
    current[31:45, 37:54] = 1.0
    mask = previous > 0

    registered, shift, confidence = _register_mask_translation(
        previous, current, mask, 24)

    assert confidence > 0.5
    np.testing.assert_allclose(shift, (6.0, 9.0), atol=0.5)
    assert np.array_equal(registered, current > 0)


def test_microsam_automatic_registered_prior_is_used_without_legacy_locks(
    monkeypatch,
) -> None:
    labels = np.zeros((30, 30), dtype=np.uint16)
    image = np.zeros((30, 30), dtype=np.float32)
    registered = np.zeros((30, 30), dtype=bool)
    registered[9:18, 12:22] = True
    captured = {}
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    def fake_predict(image_arg, positive_points, negative_points, **kwargs):
        captured.update(points=positive_points, initial_mask=kwargs["initial_mask"])
        return SimpleNamespace(
            mask=registered.copy(), bounds=(0, 30, 0, 30))

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.DEFAULT_MICROSAM_BACKEND.predict", fake_predict)

    preview = session.preview_add_edit(
        7, 1, 0, 0, 0, [], [], 20, initial_mask=registered)

    assert captured["initial_mask"] is registered
    assert captured["points"] == [(13, 16)]
    assert np.array_equal(preview["mask"], registered)


def test_registered_prototype_survives_a_collapsed_corrective_prediction(
    monkeypatch,
) -> None:
    labels = np.zeros((40, 40), dtype=np.uint16)
    image = np.zeros((40, 40), dtype=np.float32)
    prototype = np.zeros((40, 40), dtype=bool)
    prototype[12:28, 12:28] = True
    collapsed = np.zeros((40, 40), dtype=bool)
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.DEFAULT_MICROSAM_BACKEND.predict",
        lambda *args, **kwargs: SimpleNamespace(
            mask=collapsed, bounds=(0, 40, 0, 40)))

    preview = session.preview_add_edit(
        7, 1, 0, 0, 0, [(20, 29)], [], 20,
        initial_mask=prototype, continue_from_previous=True)

    assert np.array_equal(preview["mask"], prototype)


def test_positive_correction_can_replace_stale_trailing_mask() -> None:
    labels = np.zeros((40, 40), dtype=np.uint16)
    labels[10:25, 10:25] = 7
    image = np.zeros((40, 40), dtype=np.float32)
    candidate = np.zeros((40, 40), dtype=bool)
    candidate[10:25, 16:31] = True
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    session._add_edit_backend = SimpleNamespace(
        predict=lambda *args, **kwargs: SimpleNamespace(
            mask=candidate, bounds=(0, 40, 0, 40)),
        synchronize_mask=lambda *args: True,
    )

    preview = session.preview_add_edit(
        7, 0, 0, 0, 0, [(17, 28)], [], 30,
        initial_mask=labels == 7, continue_from_previous=True)

    assert np.array_equal(preview["mask"], candidate)
    assert not np.any(preview["mask"][10:25, 10:16])


def test_negative_click_can_remove_a_broader_local_area(monkeypatch) -> None:
    labels = np.zeros((40, 40), dtype=np.uint16)
    labels[10:30, 10:30] = 7
    image = np.zeros((40, 40), dtype=np.float32)
    initial_mask = labels == 7
    candidate = np.zeros((40, 40), dtype=bool)
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.DEFAULT_MICROSAM_BACKEND.predict",
        lambda *args, **kwargs: SimpleNamespace(
            mask=candidate, bounds=(0, 40, 0, 40)))
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.DEFAULT_MICROSAM_BACKEND.synchronize_mask",
        lambda *args: True)

    preview = session.preview_add_edit(
        7, 0, 0, 0, 0, [], [(20, 20)], 20,
        initial_mask=initial_mask, continue_from_previous=True)

    assert not preview["mask"][20, 24]
    assert preview["mask"][20, 26]


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
    monkeypatch.setattr(
        TrackingViewerWindow, "_request_local_segmentation", lambda *args: None)
    monkeypatch.setattr(
        TrackingViewerWindow, "_prepare_local_backend", lambda *args: None)
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
    for path, array in ((image_path, image), (track_path, tracks)):
        reader = readers[path]
        reader.axes = "TCYX"
        reader.reader = SimpleNamespace(shape=array.shape, dtype=array.dtype, img_path=path)
        reader.get_plane = lambda frame_index=0, channel=0, z_index=0, array=array: (
            SimpleNamespace(array=array[frame_index, channel], axes="YX"))
    monkeypatch.setattr(
        "fits.interaction.image.FitsIO.from_path", lambda path: readers[Path(path)])
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.FitsIO.from_path",
        lambda path: readers[Path(path)])

    empty_session = TrackingViewerSession(image_path)
    assert empty_session.started_from_image
    assert empty_session.axes == "TCYX"
    assert empty_session.track_channel_labels == ("GFP", "DAPI")
    assert not np.any(empty_session.tracked_frame())
    assert empty_session.next_track_id() == 1

    window = TrackingViewerWindow(tracking_path=track_path)

    assert window._source_path == track_path
    assert window.frame_slider.maximum() == 1
    assert window.overlay_label.text() == "Mask overlay"
    assert window.raw_image_toggle.text() == "Display raw image"
    assert window.channel_combo.currentText() == "GFP"
    assert window.mask_channel_combo.currentText() == "GFP"
    assert window.preview_split_button.text() == "Split Mask"
    assert window.preview_split_button.isCheckable()
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
    assert window.track_id_display_mode.currentData() == "selected"
    assert window.merge_tracks_button.text() == "Merge Tracks"
    assert window.stop_track_button.text() == "Split Track"
    assert window.unlink_track_button.text() == "Unlink entire track"
    assert window.delete_mask_button.text() == "Delete current mask"
    assert window.delete_track_button.text() == "Delete current track"
    assert "#b23a48" in window.delete_mask_button.styleSheet()
    assert "#8f1d2c" in window.delete_track_button.styleSheet()
    assert "#a33a3a" in window.unlink_track_button.styleSheet()
    assert window.local_cell_diameter.parent() is window.image_viewer.canvas
    assert window.local_cell_diameter.value() == 4  # From the 3x3 mask, clamped to the control minimum.
    assert window.diameter_reference.rect().width() == 4
    window.local_cell_diameter.setValue(32)
    assert window.diameter_reference.rect().width() == 32
    assert window.image_viewer.mask_item.image[3, 4, 3] == 255
    assert window._track_at_position(4, 3) == 7
    window.show_track_paths.setChecked(False)
    assert window._track_at_position(4, 3) == 7
    window.show_track_paths.setChecked(True)
    window._toggle_track_selection(7)
    assert window.track_selection_label.text() == "Selected tracks: 7"
    assert "font-weight: bold" in window.track_selection_label.styleSheet()
    _wait_trajectories(window)
    assert len(window._track_id_items) == 1
    _wait_trajectories(window)
    assert window._track_id_items[0].toPlainText() == "7"
    _wait_trajectories(window)
    assert window._track_id_items[0].pos().x() == 8
    _wait_trajectories(window)
    assert window._track_id_items[0].pos().y() == -1
    window.track_id_display_mode.setCurrentIndex(
        window.track_id_display_mode.findData("none"))
    _wait_trajectories(window)
    assert window._track_id_items == []
    window.track_id_display_mode.setCurrentIndex(
        window.track_id_display_mode.findData("selected"))
    assert window.stop_track_button.isEnabled()
    assert window.delete_mask_button.isEnabled()
    assert window.delete_track_button.isEnabled()
    assert window.unlink_track_button.isEnabled()
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
    enclosure = np.zeros((8, 8), dtype=np.uint8)
    enclosure[1, 1:7] = 1
    enclosure[6, 1:7] = 1
    enclosure[1:7, 1] = 1
    enclosure[1:7, 6] = 1
    click = np.zeros((8, 8), dtype=bool)
    click[3, 3] = True
    clicked_enclosure = enclosure.copy()
    clicked_enclosure[click] = 1
    window.image_viewer._last_drawing_base = enclosure.copy()
    window.image_viewer._last_drawing_selection = click
    window.image_viewer._last_drawing_was_click = True
    window.image_viewer._drawing_operation = "add"
    window._local_drawing_finished(clicked_enclosure)
    assert np.all(window.image_viewer.drawing_mask[2:6, 2:6])
    assert not window._local_manual_stroke

    predictions = []
    monkeypatch.setattr(
        window, "_request_local_segmentation", predictions.append)
    filled = window.image_viewer.drawing_mask
    erased = filled.copy()
    erased[click] = 0
    window.image_viewer._last_drawing_base = filled.copy()
    window.image_viewer._last_drawing_selection = click
    window.image_viewer._drawing_operation = "erase"
    window._local_drawing_finished(erased)
    assert predictions[-1]["negative_points"] == [(3, 3)]
    assert predictions[-1]["manual_stroke"] is False
    propagated = np.zeros((8, 8), dtype=bool)
    propagated[4:7, 4:7] = True
    monkeypatch.setattr(
        window._tracking_session, "_registered_temporal_mask_prior",
        lambda *args: (propagated, (1.0, 1.0), 0.9))
    window.frame_slider.setValue(1)
    window._start_local_segmentation(propagate_previous=True)
    assert np.array_equal(window.image_viewer.drawing_mask, propagated)
    assert window._local_segmentation_preview["replace_existing"] is True
    window._clear_local_segmentation_state(stop_mode=False)
    window.frame_slider.setValue(0)
    window._start_local_segmentation()
    window._switch_local_edit_target(7)
    assert window._selected_track_ids == []
    window.add_mask_button.setChecked(False)
    window.preview_split_button.setChecked(True)
    window._switch_split_target(7)
    assert window._selected_track_ids == [7]
    assert window.image_viewer._drawing_color == (
        window._other_mask_color.red(),
        window._other_mask_color.green(),
        window._other_mask_color.blue(),
    )
    assert (window.image_viewer.drawing_item.acceptedMouseButtons()
            != Qt.MouseButton.NoButton)
    assert np.all(window.image_viewer.drawing_mask[2:5, 3:6])
    guide = np.zeros((8, 8), dtype=bool)
    guide[2:5, 4] = True
    window._preview_selected_split(guide=guide)
    assert window._split_preview is not None
    window._apply_previewed_split()
    assert window.frame_slider.value() == 1
    assert window._selected_track_ids == [7]
    window._undo()
    assert window.frame_slider.value() == 0
    assert np.all(window._tracking_session.tracked_frame(0, "GFP")[2:5, 3:6] == 7)
    window._switch_split_target(7)
    assert window._selected_track_ids == []
    window.preview_split_button.setChecked(False)
    assert window.show_track_paths.isChecked()
    assert window.centroid_size.value() == 5
    window.show_centroids.setChecked(False)
    assert not window.centroid_size.isEnabled()
    window.show_centroids.setChecked(True)
    assert window.centroid_size.isEnabled()
    _wait_trajectories(window)
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
    _wait_trajectories(window)
    x_values, _ = window._track_path_items[0].getData()
    assert len(x_values) == 1
    window.frame_slider.setValue(1)
    _wait_trajectories(window)
    x_values, _ = window._track_path_items[0].getData()
    assert len(x_values) == 2
    assert not hasattr(window, "save_display_button")
    window.channel_combo.setCurrentText("DAPI")
    window.mask_channel_combo.setCurrentText("RFP")
    assert window.channel_combo.currentText() == "DAPI"
    assert window.mask_channel_combo.currentText() == "RFP"
    assert window.image_viewer.mask_item.image[1, 1, 3] == 255
    _wait_trajectories(window)
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
    _wait_trajectories(window)
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
    assert empty_window._local_manual_stroke
    assert empty_window._positive_points == []
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
        tracking_path=track_path, editing_enabled=False, selection_enabled=True)
    assert view_only_window.windowTitle() == "FITS Tracking Viewer"
    assert view_only_window.track_edit_section.isHidden()
    assert view_only_window.mask_edit_section.isHidden()
    assert view_only_window.local_cell_diameter.isHidden()
    assert view_only_window.file_filters == (FITS_MASK_TRACK,)
    assert view_only_window.display_label_edit.placeholderText() == "Optional"
    assert view_only_window.save_display_button.text() == "Save current display"
    assert view_only_window.save_display_button.isEnabled()
    view_only_window._select_single_track(7)
    assert view_only_window._selected_track_ids == [7]
    _wait_trajectories(view_only_window)
    assert [item.toPlainText() for item in view_only_window._track_id_items] == ["7"]
    view_only_window._select_single_track(11)
    assert view_only_window._selected_track_ids == [11]
    view_only_window._select_single_track(11)
    assert view_only_window._selected_track_ids == []
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
    assert "background-color: #16803b" in (
        pipeline_window.save_tracking_button.styleSheet())
    assert pipeline_window.use_original_button.text() == "Use original tracking"
    assert "background-color: #d97706" in (
        pipeline_window.use_original_button.styleSheet())
    outcomes = []
    pipeline_window.tracking_finalized.connect(outcomes.append)
    edited_path = tmp_path / "fits_track_edited.tif"
    pipeline_window._edited_tracking_saved((edited_path, {"edited": True}))
    assert outcomes == []
    assert not pipeline_window._pipeline_resolved
    pipeline_window._tracking_save_finished()
    assert len(outcomes) == 1
    assert outcomes[0].edited_path == edited_path
    assert outcomes[0].metadata == {"edited": True}
    assert pipeline_window._pipeline_resolved


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
