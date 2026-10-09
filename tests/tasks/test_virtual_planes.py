"""Viewer sources stay lazy and edited planes survive cache eviction."""

from pathlib import Path

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO

from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_TRACK
from fits.gui.viewer.tracking.session import TrackingViewerSession
from fits.interaction import FitsImageSession
from fits.interaction.planes import PlaneStore
from fits.tasks.reference_mask import ReferenceMaskSession
from fits.tasks.roi_mask import RoiSession
from fits.tasks.roi_mask.artifact import ROI_MASK_ENCODING


def test_image_session_reads_and_caches_only_requested_planes(tmp_path, monkeypatch):
    source = tmp_path / FITS_ARRAY_NAME
    array = np.arange(20 * 2 * 8 * 9, dtype=np.uint16).reshape(20, 2, 8, 9)
    tifffile.imwrite(source, array, photometric="minisblack", compression="zlib",
                     metadata={"axes": "TCYX"})
    calls = []
    original = FitsIO.get_plane
    def read(self, frame_index=0, channel=0, z_index=0):
        calls.append((frame_index, channel, z_index))
        return original(self, frame_index, channel, z_index)
    monkeypatch.setattr(FitsIO, "get_plane", read)
    monkeypatch.setattr(FitsIO, "get_array",
                        lambda *args, **kwargs: pytest.fail("Eager movie read"))
    session = FitsImageSession(source)
    assert calls == []
    np.testing.assert_array_equal(session.display_frame(7, 1), array[7, 1])
    assert not session.display_frame(7, 1).flags.writeable
    assert calls == [(7, 1, 0)]
    for frame in range(20):
        session.display_frame(frame)
    assert len(session._planes._cache) <= 8
    session.close()


def test_disk_edits_survive_eviction_and_do_not_change_source(tmp_path):
    source = tmp_path / "masks.tif"
    original = np.zeros((4, 8, 9), dtype=np.uint16)
    original[:, 2:4, 3:5] = 10
    tifffile.imwrite(source, original, photometric="minisblack", metadata={"axes": "TYX"})
    reader = FitsIO.from_path(source)
    store = PlaneStore("TYX", original.shape, reader=reader, dtype=np.uint16,
                       cache_bytes=8 * 9 * 2, cache_planes=1)
    store.writable_plane(1)[2:4, 3:5] = 20
    for frame in (0, 2, 3):
        store.plane(frame)
    assert len(store._edits) == 1
    assert store.plane(1)[2, 3] == 20
    np.testing.assert_array_equal(reader.get_array().array, original)
    assembled = store.copy()
    assert isinstance(assembled, np.memmap)
    assert assembled[1, 2, 3] == 20
    assert store._temporary is not None
    temporary = Path(store._temporary.name)
    del assembled
    store.close()
    assert not temporary.exists()


def test_read_snapshot_preserves_source_edits_and_deferred_operations(tmp_path):
    source = tmp_path / 'masks.tif'
    original = np.full((2, 8, 9), 10, dtype=np.uint16)
    tifffile.imwrite(source, original, photometric='minisblack', metadata={'axes': 'TYX'})
    store = PlaneStore('TYX', original.shape, reader=FitsIO.from_path(source), dtype=np.uint16)
    key = (0, 0, 0)
    source_state = store.snapshot_plane(key)
    store.writable_plane()[2, 3] = 20
    edited_state = store.snapshot_plane(key)
    store.hide_label(key, 10)
    hidden_state = store.snapshot_plane(key)
    store.clear_plane(key)
    cleared_state = store.snapshot_plane(key)
    store.writable_plane()[1, 1] = 30
    revision = store.revision
    np.testing.assert_array_equal(store.read_snapshot(key, source_state), original[0])
    assert store.read_snapshot(key, edited_state)[2, 3] == 20
    hidden = store.read_snapshot(key, hidden_state)
    assert hidden.sum() == 20
    assert not store.read_snapshot(key, cleared_state).any()
    assert store.revision == revision
    assert store.plane()[1, 1] == 30
    store.close()


@pytest.mark.parametrize("kind", ["reference", "roi"])
def test_loaded_mask_navigation_is_lazy_and_save_keeps_session_anchors(
        tmp_path, monkeypatch, kind):
    source = tmp_path / FITS_ARRAY_NAME
    image = np.ones((4, 8, 9), dtype=np.uint16)
    tifffile.imwrite(source, image, photometric="minisblack", metadata={"axes": "TYX"})
    labels = FitsIO.from_path(source).channel_labels
    artifact = tmp_path / f"fits_{'ref' if kind == 'reference' else 'roi'}_test.tif"
    masks = np.zeros_like(image)
    masks[1, 2:4, 3:5] = 1 if kind == "reference" else 3
    FitsIO.from_path(source).save_array(
        masks, output_path=artifact, channel_labels=labels, export_channels=labels,
        custom_metadata={"roi_mask_encoding": ROI_MASK_ENCODING} if kind == "roi" else {})
    original_get_array = FitsIO.get_array
    monkeypatch.setattr(FitsIO, "get_array",
                        lambda *args, **kwargs: pytest.fail("Eager mask read"))
    session = (ReferenceMaskSession(source, reference_path=artifact)
               if kind == "reference" else RoiSession(source, roi_path=artifact))
    assert len(session._mask._cache) == 0
    changed = session.mask_plane(1)
    changed[5, 5] = 1 if kind == "reference" else 3
    session.set_mask_plane(changed, frame_index=1)
    np.testing.assert_array_equal(session.mask_plane(1), changed)
    # Existing channel merging currently uses the full-artifact save API.
    monkeypatch.setattr(FitsIO, "get_array", original_get_array)
    session.save("test", interpolation_axis="T", overwrite=True)
    assert session.mask_plane(0).sum() == 0
    np.testing.assert_array_equal(session.mask_plane(1), changed)
    saved = FitsIO.from_path(artifact).get_array().array
    assert saved[0].sum() > 0
    session.close()


def test_tracking_real_disk_edit_save_and_undo(tmp_path, monkeypatch):
    source = tmp_path / FITS_ARRAY_NAME
    tracking = tmp_path / FITS_MASK_TRACK
    image = np.ones((4, 8, 9), dtype=np.uint16)
    masks = np.zeros_like(image)
    masks[:, 2:4, 3:5] = 10
    for path, array in ((source, image), (tracking, masks)):
        tifffile.imwrite(path, array, photometric="minisblack", compression="zlib",
                         metadata={"axes": "TYX"})
    monkeypatch.setattr(FitsIO, "get_array",
                        lambda *args, **kwargs: pytest.fail("Eager tracking read"))
    session = TrackingViewerSession(tracking)
    assert isinstance(session._tracks, PlaneStore)
    assert len(session._tracks._cache) == 0
    session.delete_mask(10, 1, 0, 0)
    for frame in (0, 2, 3):
        session.tracked_frame(frame)
    assert session.tracked_frame(1).sum() == 0
    output, _ = session.save_edited_tracking(selected_mask_channel=0)
    np.testing.assert_array_equal(FitsIO.from_path(output).get_plane(1).array, 0)
    np.testing.assert_array_equal(FitsIO.from_path(tracking).get_plane(1).array, masks[1])
    session.undo_last_edit()
    np.testing.assert_array_equal(session.tracked_frame(1), masks[1])
    session.close()


@pytest.mark.parametrize("operation", ["merge", "link", "stop", "unlink", "delete-track"])
def test_tracking_movie_edits_match_eager_results(tmp_path, operation):
    tracking = tmp_path / FITS_MASK_TRACK
    masks = np.zeros((4, 8, 9), dtype=np.uint16)
    masks[:, 1:3, 1:3] = 10
    masks[2:, 4:6, 5:7] = 20
    tifffile.imwrite(tracking, masks, photometric="minisblack", metadata={"axes": "TYX"})
    lazy = TrackingViewerSession(tracking)
    expected = masks.copy()
    if operation == "merge":
        lazy.merge_tracks((10, 20), 1, 0, 0)
        expected[expected == 20] = 10
    elif operation == "link":
        lazy.link_tracks((10, 20), 0, 0)
        expected[expected != 0] = 21
    elif operation == "stop":
        lazy.stop_track(10, 1, 0, 0)
        expected[2:][expected[2:] == 10] = 21
    elif operation == "unlink":
        lazy.unlink_track(10, 0, 0)
        for frame, new_id in ((1, 21), (2, 22), (3, 23)):
            expected[frame][expected[frame] == 10] = new_id
    else:
        lazy.delete_track(10, 0, 0)
        expected[expected == 10] = 0
    actual = np.stack([lazy.tracked_frame(frame) for frame in range(4)])
    np.testing.assert_array_equal(actual, expected)
    lazy.undo_last_edit()
    np.testing.assert_array_equal(np.stack([lazy.tracked_frame(frame) for frame in range(4)]), masks)
    lazy.close()


@pytest.mark.parametrize("kind", ["reference", "roi"])
def test_clear_current_and_stack_do_not_read_or_write_pixels(tmp_path, monkeypatch, kind):
    source = tmp_path / FITS_ARRAY_NAME
    image = np.ones((12, 2, 8, 9), dtype=np.uint16)
    tifffile.imwrite(source, image, photometric="minisblack", metadata={"axes": "TCYX"})
    artifact = tmp_path / f"fits_{'ref' if kind == 'reference' else 'roi'}_test.tif"
    labels = FitsIO.from_path(source).channel_labels
    masks = np.ones_like(image) * (1 if kind == "reference" else 3)
    FitsIO.from_path(source).save_array(
        masks, output_path=artifact, channel_labels=labels, export_channels=labels,
        custom_metadata={"roi_mask_encoding": ROI_MASK_ENCODING} if kind == "roi" else {})
    session = (ReferenceMaskSession(source, reference_path=artifact)
               if kind == "reference" else RoiSession(source, roi_path=artifact))
    with monkeypatch.context() as patch:
        patch.setattr(FitsIO, "get_plane", lambda *a, **k: pytest.fail("Clear read source pixels"))
        patch.setattr(np, "save", lambda *a, **k: pytest.fail("Clear wrote pixel data"))
        session.clear_mask_plane(frame_index=3, channel=0)
        session.clear_stack(channel=0)
    assert session._mask._temporary is None
    assert not session.mask_plane(3, 0).any()
    assert session.mask_plane(3, 1).any()
    if kind == "reference":
        session.undo_display_edit(frame_index=4, channel=0)
        np.testing.assert_array_equal(session.mask_plane(4, 0), masks[4, 0])
    edited = np.zeros((8, 9), dtype=np.uint8)
    edited[2, 2] = 1
    session.set_mask_plane(edited, frame_index=3, channel=0)
    np.testing.assert_array_equal(session.mask_plane(3, 0), edited)
    assert not session.mask_plane(2, 0).any()
    np.testing.assert_array_equal(FitsIO.from_path(artifact).get_plane(3, 0).array, masks[3, 0])
    session.close()


def test_lazy_tracking_deletion_reuses_centroids_and_undo(tmp_path, monkeypatch):
    tracking = tmp_path / FITS_MASK_TRACK
    masks = np.zeros((8, 20, 20), dtype=np.uint16)
    masks[:, 2:5, 2:5] = 10
    masks[:, 10:12, 10:12] = 20
    tifffile.imwrite(tracking, masks, photometric="minisblack", metadata={"axes": "TYX"})
    session = TrackingViewerSession(tracking)
    session.track_centroids()
    with monkeypatch.context() as patch:
        patch.setattr(FitsIO, "get_plane", lambda *a, **k: pytest.fail("Deletion rescanned source"))
        patch.setattr(np, "save", lambda *a, **k: pytest.fail("Deletion wrote plane data"))
        session.delete_track(10, 0, 0)
        assert set(session.track_centroids()) == {20}
    expected = masks.copy()
    expected[expected == 10] = 0
    np.testing.assert_array_equal(session._tracks.copy(), expected)
    session.undo_last_edit()
    np.testing.assert_array_equal(session._tracks.copy(), masks)
    session.delete_mask(10, 3, 0, 0)
    assert len(session.track_centroids()[10]) == 7
    assert session.centroid_cache.lengths[0, 0][10] == 8  # internal gap counts
    session.undo_last_edit()
    np.testing.assert_array_equal(session._tracks.copy(), masks)
    session.close()


def test_plane_snapshot_survives_later_edits_and_repeated_clearing():
    store = PlaneStore("TYX", (3, 8, 9), dtype=np.uint8)
    store.writable_plane(1)[:] = 4
    snapshot = store.snapshot_plane((1, 0, 0))
    store.writable_plane(1)[:] = 7
    store.clear_plane((1, 0, 0))
    store.restore_plane((1, 0, 0), snapshot)
    assert np.all(store.plane(1) == 4)
    store.writable_plane(1)[:] = 9
    store.restore_plane((1, 0, 0), snapshot)
    assert np.all(store.plane(1) == 4)
    store.close()
