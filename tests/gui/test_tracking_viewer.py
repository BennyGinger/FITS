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
from fits.tasks.segmentation.local_seg import SplitPredictor
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


def test_delete_track_removes_all_masks_and_is_undoable() -> None:
    tracks = np.zeros((4, 8, 8), dtype=np.uint16)
    tracks[0, 1:3, 1:3] = 7
    tracks[2, 3:5, 3:5] = 7
    tracks[1, 5:7, 5:7] = 9
    session = _editing_session(tracks)

    session.delete_track(7, 0, 0)

    assert not np.any(session._tracks == 7)
    assert np.any(session._tracks == 9)
    assert session.undo_last_edit() == 0
    assert np.count_nonzero(session._tracks == 7) == 8

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


def test_local_segmentation_adds_and_deletes_one_frame_with_auxiliary_support(
    monkeypatch,
) -> None:
    # This test exercises the deterministic classical predictor. The temporary
    # micro-SAM route has its own focused test and would otherwise load weights.
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.USE_MICROSAM_ADD_EDIT", False)
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
    session._auxiliary_mask_priors = lambda *args: ([], [])
    session._temporal_mask_prior = lambda *args: (_ for _ in ()).throw(
        AssertionError("point-driven μSAM must not request a temporal mask"))

    def fake_predict(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            mask=np.ones((20, 20), dtype=bool), bounds=(0, 20, 0, 20),
            auxiliary_weight=0.0, temporal_weight=0.0)

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
    session._auxiliary_mask_priors = lambda *args: ([], [])
    session._temporal_mask_prior = lambda *args: (_ for _ in ()).throw(
        AssertionError("legacy temporal restrictions must remain disabled"))

    def fake_predict(image_arg, positive_points, negative_points, **kwargs):
        captured.update(points=positive_points, initial_mask=kwargs["initial_mask"])
        return SimpleNamespace(
            mask=registered.copy(), bounds=(0, 30, 0, 30),
            probability=registered.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.0)

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict", fake_predict)

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
    session._auxiliary_mask_priors = lambda *args: ([], [])

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict",
        lambda *args, **kwargs: SimpleNamespace(
            mask=collapsed, bounds=(0, 40, 0, 40),
            probability=collapsed.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.0))

    preview = session.preview_add_edit(
        7, 1, 0, 0, 0, [(20, 29)], [], 20,
        initial_mask=prototype, continue_from_previous=True)

    assert np.array_equal(preview["mask"], prototype)


def test_microsam_missing_frame_uses_translated_temporal_mask_prompt(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.USE_MICROSAM_TEMPORAL_RESTRICTIONS", True)
    labels = np.zeros((20, 20), dtype=np.uint16)
    image = np.zeros((20, 20), dtype=np.float32)
    translated_prior = np.zeros((20, 20), dtype=bool)
    translated_prior[7:14, 7:14] = True
    captured = {}
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    session._auxiliary_mask_priors = lambda *args: ([], [])
    session._temporal_mask_prior = lambda *args: (translated_prior, 0.9)

    def fake_predict(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            mask=np.ones((20, 20), dtype=bool), bounds=(0, 20, 0, 20),
            auxiliary_weight=0.0, temporal_weight=0.9)

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict", fake_predict)

    session.preview_add_edit(7, 1, 0, 0, 0, [(10, 10)], [], 12)

    assert captured["initial_mask"] is translated_prior


def test_temporal_seed_applies_previous_additions_and_removals_to_current_cellpose() -> None:
    tracks = np.zeros((2, 24, 24), dtype=np.uint16)
    previous_original = np.zeros((24, 24), dtype=bool)
    previous_original[6:14, 6:14] = True
    previous_accepted = previous_original.copy()
    previous_accepted[8:12, 14:19] = True
    previous_accepted[6:8, 6:9] = False
    current_cellpose = np.zeros((24, 24), dtype=bool)
    current_cellpose[7:15, 7:15] = True
    tracks[0, previous_accepted] = 7
    tracks[1, current_cellpose] = 7
    session = _editing_session(tracks)
    session._original_add_edit_masks = {
        (0, 0, 0, 7): previous_original,
    }

    seed, weight = session._temporal_mask_prior(7, 1, 0, 0, None)

    assert seed is not None
    assert weight == 0.9
    assert np.all(seed[8:12, 14:19])
    assert not np.any(seed[6:8, 6:9])
    unchanged = current_cellpose & previous_original & previous_accepted
    assert np.all(seed[unchanged])


def test_microsam_automatic_propagation_uses_previous_mask_centroid(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.USE_MICROSAM_TEMPORAL_RESTRICTIONS", True)
    labels = np.zeros((30, 30), dtype=np.uint16)
    image = np.zeros((30, 30), dtype=np.float32)
    previous = np.zeros((30, 30), dtype=bool)
    previous[8:13, 14:21] = True
    captured = {}
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    session._auxiliary_mask_priors = lambda *args: ([], [])
    session._temporal_mask_prior = lambda *args: (previous, 0.9)

    def fake_predict(image_arg, positive_points, negative_points, **kwargs):
        captured.update(points=positive_points, initial_mask=kwargs["initial_mask"])
        return SimpleNamespace(
            mask=np.ones((30, 30), dtype=bool), bounds=(0, 30, 0, 30),
            auxiliary_weight=0.0, temporal_weight=0.9)

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict", fake_predict)

    session.preview_add_edit(7, 1, 0, 0, 0, [], [], 16)

    assert captured["points"] == [(10, 17)]
    assert captured["initial_mask"] is previous


def test_microsam_keeps_temporal_prototype_if_automatic_result_collapses(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.USE_MICROSAM_TEMPORAL_RESTRICTIONS", True)
    labels = np.zeros((30, 30), dtype=np.uint16)
    image = np.zeros((30, 30), dtype=np.float32)
    previous = np.zeros((30, 30), dtype=bool)
    previous[8:18, 10:20] = True
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    session._auxiliary_mask_priors = lambda *args: ([], [])
    session._temporal_mask_prior = lambda *args: (previous, 0.9)

    def collapsed(*args, **kwargs):
        one_pixel = np.zeros((30, 30), dtype=bool)
        one_pixel[13, 15] = True
        return SimpleNamespace(
            mask=one_pixel, bounds=(0, 30, 0, 30),
            probability=one_pixel.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.9)

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict", collapsed)

    preview = session.preview_add_edit(7, 1, 0, 0, 0, [], [], 16)

    assert np.array_equal(preview["mask"], previous)


def test_microsam_correction_does_not_translate_prior_to_edge_click(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.USE_MICROSAM_TEMPORAL_RESTRICTIONS", True)
    labels = np.zeros((30, 30), dtype=np.uint16)
    image = np.zeros((30, 30), dtype=np.float32)
    previous = np.zeros((30, 30), dtype=bool)
    previous[8:18, 10:20] = True
    anchors = []
    predictor_points = []
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    session._auxiliary_mask_priors = lambda *args: ([], [])

    def temporal(*args):
        anchors.append(args[-1])
        return previous, 0.9

    session._temporal_mask_prior = temporal

    def fake_predict(image_arg, positive_points, negative_points, **kwargs):
        predictor_points.extend(positive_points)
        return SimpleNamespace(
            mask=previous.copy(), bounds=(0, 30, 0, 30),
            probability=previous.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.9)

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict", fake_predict)

    session.preview_add_edit(
        7, 1, 0, 0, 0, [(9, 20)], [], 16,
        continue_from_previous=True)

    assert anchors == [None]
    assert predictor_points == [(12, 14), (9, 20)]


def test_microsam_edit_uses_existing_cellpose_mask_and_positive_click_only_adds(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.USE_MICROSAM_TEMPORAL_RESTRICTIONS", True)
    labels = np.zeros((30, 30), dtype=np.uint16)
    labels[8:18, 10:20] = 7
    image = np.zeros((30, 30), dtype=np.float32)
    existing = labels == 7
    working = existing.copy()
    working[14, 28] = True  # The viewer renders the click before prediction.
    candidate = np.zeros((30, 30), dtype=bool)
    candidate[12:16, 23:29] = True
    captured = {}
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    session._auxiliary_mask_priors = lambda *args: ([], [])
    session._temporal_mask_prior = lambda *args: (None, 0.0)

    def fake_predict(*args, **kwargs):
        captured["initial_mask"] = kwargs["initial_mask"]
        return SimpleNamespace(
            mask=candidate.copy(), bounds=(0, 30, 0, 30),
            probability=candidate.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.0)

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict", fake_predict)

    preview = session.preview_add_edit(
        7, 0, 0, 0, 0, [(14, 28)], [], 20,
        initial_mask=working, continue_from_previous=True)

    assert captured["initial_mask"] is not None
    assert np.array_equal(captured["initial_mask"], working)
    assert np.all(preview["mask"][existing])
    assert np.any(preview["mask"] & candidate)


def test_microsam_automatic_prototype_is_stabilized_to_prior_centroid(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.USE_MICROSAM_TEMPORAL_RESTRICTIONS", True)
    labels = np.zeros((30, 30), dtype=np.uint16)
    image = np.zeros((30, 30), dtype=np.float32)
    previous = np.zeros((30, 30), dtype=bool)
    previous[8:18, 10:20] = True
    drifted = np.zeros((30, 30), dtype=bool)
    drifted[11:21, 10:20] = True
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    session._auxiliary_mask_priors = lambda *args: ([], [])
    session._temporal_mask_prior = lambda *args: (previous, 0.9)

    def fake_predict(*args, **kwargs):
        return SimpleNamespace(
            mask=drifted.copy(), bounds=(0, 30, 0, 30),
            probability=drifted.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.9)

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict", fake_predict)

    preview = session.preview_add_edit(7, 1, 0, 0, 0, [], [], 16)

    result_center = np.mean(np.column_stack(np.nonzero(preview["mask"])), axis=0)
    prior_center = np.mean(np.column_stack(np.nonzero(previous)), axis=0)
    np.testing.assert_allclose(result_center, prior_center)


def test_microsam_propagation_resists_erosion_and_corrections_stay_local(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.USE_MICROSAM_TEMPORAL_RESTRICTIONS", True)
    labels = np.zeros((40, 40), dtype=np.uint16)
    image = np.zeros((40, 40), dtype=np.float32)
    previous = np.zeros((40, 40), dtype=bool)
    previous[10:30, 10:30] = True
    eroded = np.zeros((40, 40), dtype=bool)
    eroded[13:27, 13:27] = True
    session = object.__new__(TrackingViewerSession)
    session.image_session = SimpleNamespace(channel_labels=("GFP",))
    session.tracked_frame = lambda *args: labels
    session.display_frame = lambda *args: image
    session._resolve_channel = lambda channel: 0
    session._auxiliary_mask_priors = lambda *args: ([], [])
    session._temporal_mask_prior = lambda *args: (previous, 0.9)

    def fake_predict(*args, **kwargs):
        return SimpleNamespace(
            mask=eroded.copy(), bounds=(0, 40, 0, 40),
            probability=eroded.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.9)

    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict", fake_predict)
    propagated = session.preview_add_edit(7, 1, 0, 0, 0, [], [], 20)
    propagated_y, propagated_x = np.nonzero(propagated["mask"])
    assert int(np.min(propagated_y)) <= 11
    assert int(np.max(propagated_y)) >= 28
    assert int(np.min(propagated_x)) <= 11
    assert int(np.max(propagated_x)) >= 28
    assert not np.any(propagated["mask"] & ~previous)

    working = previous.copy()
    changed_everywhere = np.zeros((40, 40), dtype=bool)
    changed_everywhere[2:38, 2:38] = True
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict",
        lambda *args, **kwargs: SimpleNamespace(
            mask=changed_everywhere, bounds=(0, 40, 0, 40),
            probability=changed_everywhere.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.9))
    corrected = session.preview_add_edit(
        7, 1, 0, 0, 0, [(20, 29)], [], 20,
        initial_mask=working, continue_from_previous=True)
    rows, columns = np.ogrid[:40, :40]
    outside = (rows - 20) ** 2 + (columns - 29) ** 2 > 6 ** 2
    assert np.array_equal(corrected["mask"][outside], working[outside])

    removed_everywhere = np.zeros((40, 40), dtype=bool)
    monkeypatch.setattr(
        "fits.gui.viewer.tracking.session.MICROSAM_PREDICTOR.predict",
        lambda *args, **kwargs: SimpleNamespace(
            mask=removed_everywhere, bounds=(0, 40, 0, 40),
            probability=removed_everywhere.astype(float),
            auxiliary_weight=0.0, temporal_weight=0.9))
    negative = session.preview_add_edit(
        7, 1, 0, 0, 0, [], [(20, 20)], 20,
        initial_mask=working, continue_from_previous=True)
    negative_outside = (rows - 20) ** 2 + (columns - 20) ** 2 > 2 ** 2
    assert np.array_equal(negative["mask"][negative_outside], working[negative_outside])




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
        "fits.gui.viewer.tracking.window.USE_MICROSAM_REGISTERED_PRIOR", False)
    monkeypatch.setattr(
        TrackingViewerWindow, "_request_local_segmentation", lambda *args: None)
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
