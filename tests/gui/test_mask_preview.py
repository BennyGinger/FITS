"""Propagation cache equivalence, invalidation, and responsive navigation."""

from pathlib import Path
from threading import Event
from time import monotonic
from typing import cast

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO
from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fits.gui.viewer.masks.window import MaskDrawingWindow, _InterpolationOptions
from fits.interaction.mask_preview import MaskPreviewCache, PreviewCancelled
from fits.tasks.reference_mask import ReferenceMaskSession
from fits.tasks.roi_mask import RoiSession


_APP: QApplication | None = None


def app() -> QApplication:
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    return _APP


def source_image(tmp_path: Path) -> Path:
    image = np.arange(4 * 2 * 2 * 16 * 17, dtype=np.uint16).reshape(4, 2, 2, 16, 17)
    raw = tmp_path / "raw.tif"
    tifffile.imwrite(raw, image, photometric="minisblack", metadata={"axes": "TZCYX"})
    return FitsIO.from_path(raw).save_array(
        image, channel_labels=("GFP", "iRed"), output_path=tmp_path / "fits_array.tif")


@pytest.mark.parametrize("roi", [False, True])
@pytest.mark.parametrize("axis", ["T", "Z"])
def test_cached_planes_match_full_interpolation_and_follow_edits(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, roi: bool, axis: str) -> None:
    source = source_image(tmp_path)
    session = RoiSession(source) if roi else ReferenceMaskSession(source)
    first = np.zeros((16, 17), dtype=np.uint8)
    first[3:7, 4:8] = 3 if roi else 1
    last = np.roll(first, 3, axis=1)
    end = 3 if axis == "T" else 1
    coordinates = {"frame_index": end if axis == "T" else 0,
                   "z_index": 0 if axis == "T" else end, "channel": "iRed"}
    session.set_mask_plane(first, channel="iRed")
    session.set_mask_plane(last, **coordinates)
    if roi:
        # Threshold-only planes remain local; only manual overrides propagate.
        threshold = np.zeros_like(first)
        threshold[10:13, 10:13] = 4
        session.set_mask_plane(threshold, frame_index=1, channel="iRed")
    original = session.mask_array
    method = (session.interpolated_display_mask_plane if isinstance(session, RoiSession)
              else session.interpolated_mask_plane)
    complete = (session._complete_manual_corrections if isinstance(session, RoiSession)
                else session._complete_channel_mask)
    expected = complete(original, session.axes, axis, True, True)
    try:
        # Preview must not assemble the full multi-channel/Z mask stack.
        monkeypatch.setattr(session._mask, "copy", lambda *_args, **_kwargs: pytest.fail("full stack copy"))
        method(axis, channel="iRed")
        directory = session.preview_cache._directory
        assert directory is not None
        cache_path = Path(directory.name)
        assert cache_path.parent == tmp_path / ".fits" / "viewer_cache"
        assert (cache_path / "preview.npy").exists()
        assert not (cache_path / "anchors.npy").exists()
        field = "_complete_manual_corrections" if roi else "_complete_channel_mask"
        monkeypatch.setattr(session, field, lambda *_args: pytest.fail("repeated interpolation"))
        for position in range(end + 1):
            frame, z = (position, 0) if axis == "T" else (0, position)
            actual = method(axis, frame_index=frame, channel="iRed", z_index=z)
            target = expected[frame, z, 1]
            np.testing.assert_array_equal(actual, (target >= 3).astype(np.uint8) if roi else target)
        monkeypatch.undo()
        np.testing.assert_array_equal(session.mask_array, original)
        previous_key = session.preview_cache.key
        session.set_mask_plane(first, **coordinates)
        method(axis, **coordinates)
        assert session.preview_cache.key != previous_key
        assert not cache_path.exists()
    finally:
        directory = session.preview_cache._directory
        session.close()
        assert directory is None or not Path(directory.name).exists()


def test_cancelled_preview_does_not_publish_or_leave_temporary_files(tmp_path: Path) -> None:
    cache = MaskPreviewCache(tmp_path / "fits_array.tif")
    count = 0
    def read(_index: int):
        nonlocal count
        count += 1
        return np.ones((4, 4), dtype=np.uint8)
    with pytest.raises(PreviewCancelled):
        cache.plane((1,), 0, count=4, shape=(4, 4), read=read,
                    complete=lambda anchors: anchors, cancelled=lambda: count == 2)
    assert cache.key is None
    assert not list((tmp_path / ".fits" / "viewer_cache").iterdir())


def test_preview_separates_channels_depths_and_extrapolation_options(tmp_path: Path) -> None:
    session = ReferenceMaskSession(source_image(tmp_path))
    anchor = np.zeros((16, 17), dtype=np.uint8)
    anchor[3:7, 4:8] = 1
    session.set_mask_plane(anchor, frame_index=1, channel="iRed")
    session.set_mask_plane(anchor, frame_index=3, channel="iRed")
    try:
        without_extension = session.interpolated_mask_plane(
            "T", channel="iRed", extrapolate_start=False)
        assert not np.any(without_extension)
        np.testing.assert_array_equal(
            session.interpolated_mask_plane("T", channel="iRed"), anchor)
        assert not np.any(session.interpolated_mask_plane("T", channel="GFP"))
        assert not np.any(session.interpolated_mask_plane("T", channel="iRed", z_index=1))
        assert len(list((tmp_path / ".fits" / "viewer_cache").iterdir())) == 1
    finally:
        session.close()


def test_preview_uses_system_temp_when_experiment_cache_is_unwritable(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fits.interaction.mask_preview as preview
    temporary = preview.TemporaryDirectory
    def fallback(*args, **kwargs):
        if "dir" in kwargs:
            raise PermissionError("read-only experiment")
        return temporary(*args, **kwargs)
    monkeypatch.setattr(preview, "TemporaryDirectory", fallback)
    cache = MaskPreviewCache(tmp_path / "fits_array.tif")
    try:
        plane = cache.plane((1,), 0, count=3, shape=(4, 4),
                            read=lambda _: np.ones((4, 4), dtype=np.uint8),
                            complete=lambda anchors: anchors)
        assert np.all(plane == 1)
        assert cache._directory is not None
        assert Path(cache._directory.name).parent != tmp_path / ".fits" / "viewer_cache"
    finally:
        cache.close()


def wait_preview(window: MaskDrawingWindow) -> None:
    deadline = monotonic() + 5
    while window._preview_thread is not None:
        app().processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, window.status_label.text()


def test_navigation_stays_responsive_during_background_preview(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    application = app()
    source = source_image(tmp_path)
    window = MaskDrawingWindow()
    window._open_source(source)
    session = window._reference_session
    assert session is not None
    anchor = np.zeros((16, 17), dtype=np.uint8)
    anchor[3:7, 4:8] = 1
    session.set_mask_plane(anchor, frame_index=0, channel="iRed")
    session.set_mask_plane(anchor, frame_index=3, channel="iRed")
    window.channel_combo.setCurrentText("iRed")
    started, release = Event(), Event()
    complete = session._prepare_preview_sequence
    def delayed(*args):
        assert QThread.currentThread() != application.thread()
        started.set()
        assert release.wait(5)
        return complete(*args)
    monkeypatch.setattr(session, "_prepare_preview_sequence", delayed)
    try:
        window.reference_panel.live_preview.setChecked(True)
        assert started.wait(2)
        assert not window.progress.isHidden()
        window.frame_slider.setValue(2)
        assert window.frame_slider.value() == 2
        assert not np.any(window.image_viewer.drawing_mask)
        release.set()
        wait_preview(window)
        np.testing.assert_array_equal(window.image_viewer.drawing_mask, anchor)
        assert window.progress.isHidden()
        monkeypatch.setattr(session, "_complete_channel_mask",
                            lambda *_args: pytest.fail("navigation recalculated preview"))
        for frame in (3, 0, 1, 2):
            window.frame_slider.setValue(frame)
            np.testing.assert_array_equal(window.image_viewer.drawing_mask, anchor)
            assert window._preview_thread is None
        # Saving a visible interpolated frame must retain its original anchors
        # and reuse the completed sequence rather than invalidating it.
        revision = session._mask.revision
        key = session.preview_cache.key
        window.reference_panel.label_edit.setText("cached")
        window._save_reference_mask()
        assert (tmp_path / "fits_ref_cached.tif").is_file(), window.status_label.text()
        assert session._mask.revision == revision
        assert session.preview_cache.key == key
        assert not np.any(session.mask_plane(2, "iRed"))
    finally:
        release.set()
        window.close()


def test_drawing_cancels_stale_preview_and_keeps_new_anchors(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app()
    window = MaskDrawingWindow()
    window._open_source(source_image(tmp_path))
    session = window._reference_session
    assert session is not None
    anchor = np.zeros((16, 17), dtype=np.uint8)
    anchor[3:7, 4:8] = 1
    session.set_mask_plane(anchor, frame_index=0)
    session.set_mask_plane(anchor, frame_index=3)
    started, release = Event(), Event()
    complete = session._prepare_preview_sequence
    def delayed(*args):
        started.set()
        assert release.wait(5)
        return complete(*args)
    monkeypatch.setattr(session, "_prepare_preview_sequence", delayed)
    try:
        window.reference_panel.live_preview.setChecked(True)
        assert started.wait(2)
        window._disable_active_interpolation_preview()
        edited = np.roll(anchor, 2, axis=1)
        session.set_mask_plane(edited, frame_index=0)
        window._display_selection()
        release.set()
        wait_preview(window)
        assert session.preview_cache.key is None
        np.testing.assert_array_equal(window.image_viewer.drawing_mask, edited)
    finally:
        release.set()
        window.close()


@pytest.mark.parametrize("roi", [False, True])
@pytest.mark.parametrize("axis", ["T", "Z"])
@pytest.mark.parametrize("uncached", [False, True])
def test_save_reuses_preview_and_preserves_encoded_states(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, roi: bool, axis: str,
        uncached: bool) -> None:
    session = RoiSession(source_image(tmp_path)) if roi else ReferenceMaskSession(source_image(tmp_path))
    first = np.zeros((16, 17), dtype=np.uint8)
    first[3:7, 4:8] = 3 if roi else 1
    last = np.roll(first, 3, axis=1)
    end = 3 if axis == "T" else 1
    session.set_mask_plane(first, channel="iRed")
    session.set_mask_plane(last, channel="iRed",
                           frame_index=end if axis == "T" else 0,
                           z_index=end if axis == "Z" else 0)
    if roi:
        states = first.copy()
        states[10:12, 2:4] = 4
        states[10:12, 5:7] = 2
        states[10:12, 8:10] = 5
        session.set_mask_plane(states, channel="iRed")
    if uncached:
        session.set_mask_plane(first, channel="iRed",
                               frame_index=1 if axis == "Z" else 0,
                               z_index=1 if axis == "T" else 0)
    original = session.mask_array
    complete = (session._complete_manual_corrections if isinstance(session, RoiSession)
                else session._complete_channel_mask)
    expected = complete(session._channel_mask(1), "TZYX", axis, True, True)
    method = (session.interpolated_display_mask_plane if isinstance(session, RoiSession)
              else session.interpolated_mask_plane)
    method(axis, channel="iRed")
    calls = []
    def remaining(sequence, axes, requested_axis, start, end):
        calls.append(sequence.shape)
        return complete(sequence, axes, requested_axis, start, end)
    name = "_complete_manual_corrections" if roi else "_complete_channel_mask"
    monkeypatch.setattr(session, name, remaining)
    read_plane = session.mask_plane
    def uncached_plane(frame=0, channel=0, z=0):
        assert (z if axis == 'T' else frame) != 0, 'save reread a cached sequence'
        return read_plane(frame, channel, z)
    monkeypatch.setattr(session, 'mask_plane', uncached_plane)
    try:
        output = session.save("cached", channel="iRed", interpolation_axis=axis,
                              compression=None)
        np.testing.assert_array_equal(FitsIO.from_path(output).get_array().array, expected)
        # Only an uncached, populated fixed-Z/T sequence requires calculation.
        assert len(calls) == int(uncached)
        np.testing.assert_array_equal(session.mask_array, original)
        calls.clear()
        monkeypatch.setattr(session, 'mask_plane', read_plane)
        session.set_mask_plane(last, channel="iRed")
        session.save("cached", channel="iRed", interpolation_axis=axis,
                     overwrite=True, compression=None)
        assert calls  # An edit invalidates the old result for saving too.
    finally:
        session.close()


def test_progressive_cache_prioritizes_navigation_and_never_saves_partial_output(tmp_path: Path):
    cache = MaskPreviewCache(tmp_path / 'fits_array.tif')
    center = 3
    visited = []
    key = ('progressive',)
    def ready(index):
        nonlocal center
        visited.append(index)
        cached = cache.cached_plane(key, index)
        assert cached is not None
        np.testing.assert_array_equal(cached, index)
        if len(visited) < 7:
            assert not cache.copy_into(key, np.empty((7, 4, 5), dtype=np.uint8))
        if len(visited) == 2:
            center = 6
            assert cache.cached_plane(key, 6) is None
    try:
        cache.prepare(key, count=7, shape=(4, 5),
                      read=lambda index: np.full((4, 5), index, dtype=np.uint8),
                      prepare=lambda anchors: lambda index: anchors[index],
                      priority=lambda: center, cancelled=lambda: False,
                      ready=ready, progress=lambda message: None)
        assert visited[:3] == [3, 2, 6]
        assert cache.contains(key)
        output = np.empty((7, 4, 5), dtype=np.uint8)
        assert cache.copy_into(key, output)
        for index in range(7):
            assert np.all(output[index] == index)
    finally:
        cache.close()


@pytest.mark.parametrize('roi', [False, True])
@pytest.mark.parametrize('axis', ['T', 'Z'])
def test_progressive_session_matches_full_encoded_interpolation(tmp_path: Path, roi: bool, axis: str):
    session = RoiSession(source_image(tmp_path)) if roi else ReferenceMaskSession(source_image(tmp_path))
    first = np.zeros((16, 17), dtype=np.uint8)
    first[3:6, 4:7] = 3 if roi else 1
    if roi:
        first[10:13, 4:7] = 2
        first[5:7, 12:15] = 4
    session.set_mask_plane(first, channel='iRed')
    session.set_mask_plane(np.roll(first, 2, axis=1), channel='iRed',
                           frame_index=3 if axis == 'T' else 0,
                           z_index=1 if axis == 'Z' else 0)
    complete = (session._complete_manual_corrections if isinstance(session, RoiSession)
                else session._complete_channel_mask)
    expected = complete(session._channel_mask(1), 'TZYX', axis, True, False)
    options: _InterpolationOptions = {"frame_index": 0, "channel": "iRed", "z_index": 0,
                                      "extrapolate_start": True, "extrapolate_end": False}
    try:
        session.prepare_preview(axis, **options, priority=lambda: 1, cancelled=lambda: False,
                                ready=lambda index: None, progress=lambda message: None)
        key = session.preview_key(axis, **options)
        for index in range(session.frame_count if axis == 'T' else session.plane_count):
            target = expected[index, 0] if axis == 'T' else expected[0, index]
            cached = session.preview_cache.cached_plane(key, index)
            assert cached is not None
            np.testing.assert_array_equal(cached, target)
        monkey_output = session.save('progressive', channel='iRed', interpolation_axis=axis,
                                     extrapolate_end=False)
        np.testing.assert_array_equal(FitsIO.from_path(monkey_output).get_array().array, expected)
    finally:
        session.close()


def test_ready_frames_remain_usable_and_missing_frames_dim_during_progress(tmp_path: Path, monkeypatch):
    app()
    window = MaskDrawingWindow()
    window._open_source(source_image(tmp_path))
    session = window._reference_session
    assert session is not None
    mask = np.zeros((16, 17), dtype=np.uint8)
    mask[3:6, 4:7] = 1
    session.set_mask_plane(mask, frame_index=0)
    session.set_mask_plane(mask, frame_index=3)
    blocked, release = Event(), Event()
    prepare = session._prepare_preview_sequence
    def delayed(*args):
        build = prepare(*args)
        def plane(index):
            if index != 0:
                blocked.set()
                assert release.wait(5)
            return build(index)
        return plane
    monkeypatch.setattr(session, '_prepare_preview_sequence', delayed)
    try:
        window.reference_panel.live_preview.setChecked(True)
        assert blocked.wait(2)
        app().processEvents()
        assert not window.image_viewer._loading_visible
        window.frame_slider.setValue(3)
        assert window.image_viewer._loading_visible
        window.frame_slider.setValue(0)
        assert not window.image_viewer._loading_visible
        window.frame_slider.setValue(3)
        release.set()
        wait_preview(window)
        assert not window.image_viewer._loading_visible
        QTest.qWait(200)
        assert window.image_viewer.loading_overlay.isHidden()
        np.testing.assert_array_equal(window.image_viewer.drawing_mask, mask)
    finally:
        release.set()
        window.close()


def test_saving_during_partial_preview_writes_complete_mask(tmp_path: Path):
    session = ReferenceMaskSession(source_image(tmp_path))
    mask = np.zeros((16, 17), dtype=np.uint8)
    mask[3:6, 4:7] = 1
    session.set_mask_plane(mask)
    session.set_mask_plane(np.roll(mask, 3, axis=1), frame_index=3)
    expected = session._complete_channel_mask(session._channel_mask(0), 'TZYX', 'T', True, True)
    saved = []
    def ready(index):
        if not saved:
            saved.append(session.save('partial', interpolation_axis='T'))
    try:
        session.prepare_preview('T', frame_index=0, channel=0, z_index=0,
                                extrapolate_start=True, extrapolate_end=True,
                                priority=lambda: 0, cancelled=lambda: False,
                                ready=ready, progress=lambda message: None)
        np.testing.assert_array_equal(FitsIO.from_path(saved[0]).get_array().array, expected)
    finally:
        session.close()
