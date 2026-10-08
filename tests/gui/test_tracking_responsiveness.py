"""Background trajectories, incremental edits, and initial mask channel selection."""
from pathlib import Path
from threading import Event
from time import monotonic
from typing import cast

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO
from PySide6.QtCore import QPointF, QThread
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionGraphicsItem

from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_TRACK
from fits.gui.viewer.masks.window import MaskDrawingWindow
from fits.gui.viewer.tracking.centroids import CentroidCache
from fits.gui.viewer.tracking.path_item import TrackPathsItem
from fits.gui.viewer.tracking.session import TrackingViewerSession
from fits.gui.viewer.tracking.window import TrackingViewerWindow
from fits.tasks.roi_mask.artifact import ROI_MASK_ENCODING


_APP: QApplication | None = None


def app() -> QApplication:
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    return _APP


def wait_ready(window: TrackingViewerWindow) -> None:
    deadline = monotonic() + 5
    while (window._trajectory_thread is not None
           or window._trajectory_ready_key != window._trajectory_key()):
        app().processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, window.status_label.text()


def experiment(tmp_path: Path, channels: tuple[str, ...] = ("GFP", "DAPI", "iRed")) -> Path:
    raw = tmp_path / "raw.tif"
    image = np.ones((4, len(channels), 24, 25), dtype=np.uint16)
    for channel in range(len(channels)):
        image[:, channel] *= channel + 1
    tifffile.imwrite(raw, image, photometric="minisblack", metadata={"axes": "TCYX"})
    return FitsIO.from_path(raw).save_array(image, channel_labels=channels,
                                           output_path=tmp_path / FITS_ARRAY_NAME)


def mask(source: Path, name: str, channels: tuple[str, ...], value: int = 7) -> Path:
    labels = np.zeros((4, len(channels), 24, 25), dtype=np.uint16)
    labels[:, :, 4:7, 5:8] = value
    return FitsIO.from_path(source).save_array(
        labels[:, 0] if len(channels) == 1 else labels,
        channel_labels=("GFP", "DAPI", "iRed"), export_channels=channels,
        output_path=source.with_name(name),
        custom_metadata={"roi_mask_encoding": ROI_MASK_ENCODING} if "roi" in name else {})


@pytest.mark.parametrize("channels", [("iRed",), ("iRed", "GFP")])
def test_tracking_opens_first_mask_channel_in_raw_image(tmp_path: Path, channels: tuple[str, ...]) -> None:
    app()
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, channels)
    window = TrackingViewerWindow(tracking_path=tracking)
    try:
        assert window.mask_channel_combo.currentText() == "iRed"
        assert window.channel_combo.currentText() == "iRed"
        image = window.image_viewer.image_item.image
        assert image is not None
        np.testing.assert_array_equal(image, 3)
        wait_ready(window)
    finally:
        window.close()


@pytest.mark.parametrize("kind", ["ref", "roi"])
@pytest.mark.parametrize("channels", [("iRed",), ("iRed", "GFP")])
def test_binary_viewer_opens_first_available_mask_channel(
        tmp_path: Path, kind: str, channels: tuple[str, ...]) -> None:
    app()
    source = experiment(tmp_path)
    mask(source, f"fits_{kind}_test.tif", channels, 1 if kind == "ref" else 4)
    window = MaskDrawingWindow()
    try:
        window._open_source(source)
        assert window.channel_combo.currentText() == "iRed", window.status_label.text()
        image = window.image_viewer.image_item.image
        assert image is not None
        np.testing.assert_array_equal(image, 3)
    finally:
        window.close()


def test_image_navigation_and_progress_while_centroids_are_busy(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    application = app()
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    started, release = Event(), Event()
    read = TrackingViewerSession.centroid_frame
    def slow_read(self: TrackingViewerSession, frame_index: int = 0,
                  channel: int = 0, z_index: int = 0):
        if QThread.currentThread() != application.thread():
            started.set()
            assert release.wait(5)
        return read(self, frame_index, channel, z_index)
    monkeypatch.setattr(TrackingViewerSession, "centroid_frame", slow_read)
    window = TrackingViewerWindow(tracking_path=tracking)
    try:
        assert started.wait(2)
        assert not window.trajectory_progress.isHidden()
        assert "centroid" in window.trajectory_status.text()
        assert window.image_viewer.view_box.opacity() == 0.0
        window.show()
        application.processEvents()
        assert window.image_viewer.view_box.geometry().width() > 0
        display = window.image_viewer.canvas.grab().toImage()
        assert display.pixelColor(display.width() // 2, display.height() // 2) == QColor("black")
        window.frame_slider.setValue(2)
        assert window.frame_slider.value() == 2
        assert window.image_viewer.mask_item.image is not None
        assert window.image_viewer.view_box.opacity() == 0.0
        release.set()
        wait_ready(window)
        assert window.trajectory_progress.isHidden()
        assert window.image_viewer.view_box.isVisible()
        assert window.image_viewer.view_box.opacity() == 1.0
        assert window.image_viewer.view_box.geometry().width() > 0
        # Visible alone is insufficient: ensure the loaded mask actually paints.
        canvas = window.image_viewer.canvas
        mask_position = canvas.mapFromScene(
            window.image_viewer.view_box.mapViewToScene(QPointF(6, 5)))
        display = canvas.grab().toImage()
        assert display.pixelColor(mask_position) != QColor("black")
        item = window._track_path_items[0]
        window.frame_slider.setValue(3)
        assert window._track_path_items[0] is item
        window.path_extent.setCurrentIndex(window.path_extent.findData("full"))
        image_key = item._image.cacheKey()
        window.frame_slider.setValue(0)
        assert item._image.cacheKey() == image_key
        assert window._trajectory_thread is None
    finally:
        release.set()
        window.close()


def test_failed_loading_restores_display(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    application = app()
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    def fail_read(*_args, **_kwargs):
        raise RuntimeError("centroid read failed")
    monkeypatch.setattr(TrackingViewerSession, "centroid_frame", fail_read)
    window = TrackingViewerWindow(tracking_path=tracking)
    try:
        window.show()
        deadline = monotonic() + 5
        while window._trajectory_thread is not None:
            application.processEvents()
            QTest.qWait(5)
            assert monotonic() < deadline
        assert "centroid read failed" in window.status_label.text()
        assert window.trajectory_progress.isHidden()
        assert window.image_viewer.view_box.opacity() == 1.0
        assert window.image_viewer.view_box.geometry().width() > 0
        canvas = window.image_viewer.canvas
        mask_position = canvas.mapFromScene(
            window.image_viewer.view_box.mapViewToScene(QPointF(6, 5)))
        assert canvas.grab().toImage().pixelColor(mask_position) != QColor("black")
    finally:
        window.close()


def test_centroid_cache_recomputes_only_edited_frame_and_undo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    session = TrackingViewerSession(tracking)
    read = session.centroid_frame
    calls: list[int] = []
    def recorded(frame_index: int = 0, channel: int = 0, z_index: int = 0):
        calls.append(frame_index)
        return read(frame_index, channel, z_index)
    monkeypatch.setattr(session, "centroid_frame", recorded)
    try:
        session.track_centroids()
        assert calls == [0, 1, 2, 3]
        session.delete_mask(7, 1, 0, 0)
        calls.clear()
        assert session.track_centroids()[7][:, 0].tolist() == [0, 2, 3]
        assert calls == [1]
        session.undo_last_edit()
        calls.clear()
        assert session.track_centroids()[7][:, 0].tolist() == [0, 1, 2, 3]
        assert calls == [1]
    finally:
        session.close()


def test_disk_centroids_reused_but_rejected_after_source_changes(tmp_path: Path) -> None:
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    session = TrackingViewerSession(tracking)
    expected = session.track_centroids()
    session.close()
    target = tracking.parent / ".fits" / "viewer_cache" / f"{tracking.name}.centroids-c0-z0.npz"
    assert target.exists()
    with np.load(target, allow_pickle=False) as saved:
        assert saved["track_ids"].tolist() == [7]
        assert saved["track_lengths"].tolist() == [4]
    def forbidden(*_args):
        pytest.fail("Unchanged movie should use its centroid disk cache")
    cache = CentroidCache()
    cached = cache.calculate(forbidden, count=4, channel=0, z=0, source=tracking)
    assert cached is not None
    np.testing.assert_array_equal(cached[7], expected[7])
    tracking.touch()
    calls: list[int] = []
    def read(frame: int, _channel: int, _z: int):
        calls.append(frame)
        return np.ones((3, 4), dtype=np.uint16)
    changed = CentroidCache().calculate(read, count=4, channel=0, z=0, source=tracking)
    assert changed is not None and set(changed) == {1}
    assert calls == [0, 1, 2, 3]


def test_legacy_centroid_cache_migrates_without_rescanning(tmp_path: Path) -> None:
    from fits.gui.viewer.tracking.centroids import _cache_path, _signature
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    legacy = tracking.with_name(f".{tracking.name}.centroids-c0-z0.npz")
    # Old caches contain only observations; a missing middle frame counts in length.
    points = np.asarray([[0, 6, 5], [3, 6, 5]], dtype=np.float64)
    np.savez_compressed(legacy, signature=_signature(tracking),
                        ids=np.asarray([7, 7]), points=points)
    def forbidden(*_args):
        pytest.fail("Migration must reuse existing observations")
    cache = CentroidCache()
    loaded = cache.calculate(forbidden, count=4, channel=0, z=0, source=tracking)
    assert loaded is not None
    np.testing.assert_array_equal(loaded[7], points)
    assert cache.matching(0, 0, "eq", 4) == {7}
    assert not legacy.exists()
    with np.load(_cache_path(tracking, 0, 0), allow_pickle=False) as saved:
        assert saved["track_lengths"].tolist() == [4]


def test_length_filters_reuse_results_and_invalidate_after_edits() -> None:
    cache = CentroidCache()
    def read(frame: int, _channel: int, _z: int):
        plane = np.zeros((3, 4), dtype=np.uint16)
        if frame in (0, 3):
            plane[1, 1] = 7
        return plane
    assert cache.calculate(read, count=4, channel=0, z=0) is not None
    accepted = cache.matching(0, 0, "ge", 3)
    assert accepted == {7}
    assert cache.matching(0, 0, "ge", 3) is accepted
    cache.invalidate(0, 0, (3,))
    assert not cache.matches
    assert cache.calculate(lambda *_: np.zeros((3, 4), dtype=np.uint16),
                           count=4, channel=0, z=0) is not None
    assert cache.matching(0, 0, "ge", 3) == set()
    assert cache.matching(0, 0, "eq", 1) == {7}


def test_unwritable_centroid_cache_keeps_memory_filters_working(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fits.gui.viewer.tracking.centroids as centroids
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    def denied(*_args, **_kwargs):
        raise PermissionError("read-only experiment")
    monkeypatch.setattr(centroids, "NamedTemporaryFile", denied)
    cache = CentroidCache()
    assert cache.calculate(lambda *_: np.ones((3, 4), dtype=np.uint16),
                           count=4, channel=0, z=0, source=tracking) is not None
    assert cache.matching(0, 0, "eq", 4) == {1}
    assert not list((tmp_path / ".fits" / "viewer_cache").glob("*.tmp"))


def test_filter_changes_reuse_drawings_for_recent_or_equivalent_selections(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fits.gui.viewer.tracking.window as tracking_window
    app()
    source = experiment(tmp_path)
    labels = np.zeros((4, 24, 25), dtype=np.uint16)
    labels[:, 4:7, 5:8] = 7
    labels[1:3, 14:17, 15:18] = 8
    tracking = FitsIO.from_path(source).save_array(
        labels, channel_labels=("GFP", "DAPI", "iRed"), export_channels=("iRed",),
        output_path=source.with_name(FITS_MASK_TRACK))
    window = TrackingViewerWindow(tracking_path=tracking)
    try:
        wait_ready(window)
        all_tracks = window._track_path_items[0]._prepared
        window.filter_value.setValue(3)
        window.filter_tracks.setChecked(True)
        wait_ready(window)
        filtered = window._track_path_items[0]._prepared
        assert filtered is not None and set(filtered.tracks) == {7}
        assert filtered is not all_tracks
        def forbidden(*_args, **_kwargs):
            pytest.fail("Cached or equivalent filters must not start another drawing")
        monkeypatch.setattr(tracking_window, "prepare_paths", forbidden)
        for minimum in (4, 3):
            window.filter_value.setValue(minimum)
            assert window._track_path_items[0]._prepared is filtered
            assert window._trajectory_thread is None
        window.filter_tracks.setChecked(False)
        assert window._track_path_items[0]._prepared is all_tracks
        assert window._trajectory_thread is None
        window.filter_tracks.setChecked(True)
        assert window._track_path_items[0]._prepared is filtered
        assert window._trajectory_thread is None
        assert window.image_viewer.view_box.opacity() == 1.0
        # Returning to a cached filter must reveal it even during another drawing.
        started = Event()
        def delayed(*_args, **_kwargs):
            started.set()
            deadline = monotonic() + 5
            while not QThread.currentThread().isInterruptionRequested():
                assert monotonic() < deadline
                Event().wait(0.005)
            return None
        monkeypatch.setattr(tracking_window, "prepare_paths", delayed)
        window.filter_value.setValue(5)
        assert started.wait(2)
        assert window.image_viewer.view_box.opacity() == 0.0
        window.filter_value.setValue(3)
        assert window._track_path_items[0]._prepared is filtered
        assert window.image_viewer.view_box.opacity() == 1.0
        wait_ready(window)
        # Edited masks must discard drawings prepared from the previous revision.
        monkeypatch.undo()
        session = window._tracking_session
        assert session is not None
        session.delete_mask(7, 0, "iRed", 0)
        window._display_selection()
        wait_ready(window)
        edited = window._track_path_items[0]._prepared
        assert edited is not None and edited is not filtered
        assert edited.tracks[7][:, 0].tolist() == [1, 2, 3]
    finally:
        window.close()


def test_large_drawings_are_displayed_without_retaining_over_budget_cache(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fits.gui.viewer.tracking.window as tracking_window
    app()
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    monkeypatch.setattr(tracking_window, "TRAJECTORY_CACHE_BYTES", 1)
    window = TrackingViewerWindow(tracking_path=tracking)
    try:
        wait_ready(window)
        assert not window._trajectory_cache
        assert window._track_path_items[0]._prepared is not None
        assert window.image_viewer.view_box.opacity() == 1.0
    finally:
        window.close()


def test_centroid_result_invalidated_during_calculation_is_discarded() -> None:
    cache = CentroidCache()
    def read(frame: int, _channel: int, _z: int):
        cache.invalidate(0, 0, (frame,))
        return np.ones((3, 4), dtype=np.uint16)
    assert cache.calculate(read, count=2, channel=0, z=0) is None
    assert cache.cached(0, 0) is None


def test_incremental_paths_match_rebuilt_drawing_when_seeking_backwards() -> None:
    app()
    points = np.asarray([[0, 4, 4], [1, 8, 8], [3, 16, 4]], dtype=float)
    item = TrackPathsItem()
    def draw(path: TrackPathsItem) -> QImage:
        image = QImage(24, 24, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        path.paint(painter, QStyleOptionGraphicsItem())
        painter.end()
        return image
    item.set_tracks({7: points}, color_for=lambda _: QColor("red"), thickness=2,
                    show_markers=True, marker_size=3)
    for frame in (0, 1, 2, 3, 1, 0, 3):
        item.set_frame(frame, full=False)
        rebuilt = TrackPathsItem()
        rebuilt.set_tracks({7: points[points[:, 0] <= frame]}, color_for=lambda _: QColor("red"),
                           thickness=2, show_markers=True, marker_size=3)
        assert draw(item) == draw(rebuilt)


def test_switching_experiment_cancels_old_drawing_worker(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from time import sleep
    import fits.gui.viewer.tracking.window as tracking_window
    app()
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    second = tmp_path / "second"
    second.mkdir()
    second_source = experiment(second)
    second_tracking = mask(second_source, FITS_MASK_TRACK, ("GFP",))
    started = Event()
    prepare = tracking_window.prepare_paths
    calls = 0
    def delayed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            while not QThread.currentThread().isInterruptionRequested():
                sleep(0.005)
            return None
        return prepare(*args, **kwargs)
    monkeypatch.setattr(tracking_window, "prepare_paths", delayed)
    window = TrackingViewerWindow(tracking_path=tracking)
    try:
        assert started.wait(2)
        window._open_source(second_tracking)
        wait_ready(window)
        assert window._source_path == second_tracking
        assert window.channel_combo.currentText() == "GFP"
        assert window._trajectory_failed_key is None
        assert set(window._visible_centroids) == {7}
        assert window.image_viewer.view_box.opacity() == 1.0
    finally:
        window.close()


def test_cancelled_centroids_resume_without_reading_completed_frames() -> None:
    cache = CentroidCache()
    calls: list[int] = []
    def read(frame: int, _channel: int, _z: int):
        calls.append(frame)
        return np.ones((3, 4), dtype=np.uint16)
    assert cache.calculate(read, count=4, channel=0, z=0, cancelled=lambda: len(calls) == 2) is None
    assert cache.calculate(read, count=4, channel=0, z=0) is not None
    assert calls == [0, 1, 2, 3]


def test_frame_jumps_use_prepared_overlays_without_redrawing_or_starting_workers(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fits.gui.viewer.tracking.path_item as path_item
    app()
    source = experiment(tmp_path)
    tracking = mask(source, FITS_MASK_TRACK, ("iRed",))
    window = TrackingViewerWindow(tracking_path=tracking)
    try:
        wait_ready(window)
        def forbidden(*_args, **_kwargs):
            pytest.fail("Frame navigation must not draw trajectories again")
        monkeypatch.setattr(path_item, "_draw", forbidden)
        item = window._track_path_items[0]
        assert item._prepared is not None
        assert isinstance(item._prepared.frames, np.memmap)
        for frame in (3, 1, 0, 2, 3, 0):
            window.frame_slider.setValue(frame)
            assert item._frame == frame
            assert item.isVisible()
            assert window._trajectory_thread is None
            assert window.trajectory_progress.isHidden()
            assert len(item.getData()[0]) == frame + 1
    finally:
        window.close()


def test_prepared_overlays_cover_empty_frames_gaps_and_frames_after_last_observation() -> None:
    app()
    points = np.asarray([[3, 4, 4], [5, 8, 8]], dtype=float)
    item = TrackPathsItem()
    item.set_tracks({7: points}, color_for=lambda _: QColor("red"), thickness=2,
                    show_markers=True, marker_size=3)
    assert item._prepared is not None
    for frame in (0, 2, 3, 4, 5, 9, 1):
        item.set_frame(frame, full=False)
        image = item._image
        alpha = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)[:, :, 3]
        assert bool(np.any(alpha)) == (frame >= 3)
        assert len(item.getData()[0]) == int(frame >= 3) + int(frame >= 5)
    item.set_frame(9, full=False)
    assert item._image == item._prepared.full_image


def test_overlay_image_keeps_mapped_storage_alive_until_released() -> None:
    import gc
    import weakref
    from fits.gui.viewer.tracking.path_item import prepare_paths
    prepared = prepare_paths(
        {7: np.asarray([[0, 4, 4], [1, 8, 8]], dtype=float)},
        color_for=lambda _: QColor("red"), thickness=2, show_markers=True, marker_size=3)
    assert prepared is not None and prepared.frames is not None
    storage = weakref.ref(prepared.frames)
    image = prepared.image(0)
    del prepared
    gc.collect()
    assert storage() is not None
    assert not image.isNull()
    del image
    gc.collect()
    assert storage() is None
