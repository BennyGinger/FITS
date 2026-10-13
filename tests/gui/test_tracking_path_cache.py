"""Completed drawings survive reopening; stale and partial drawings do not."""
import json

import numpy as np
import pytest
from PySide6.QtGui import QColor

from fits.gui.viewer.tracking.path_cache import PathDrawingCache
from fits.gui.viewer.tracking.path_item import prepare_paths


STYLE = {"single": False, "color": "#ffd700", "thickness": 2, "markers": True, "size": 3}


def drawing(tmp_path):
    source = tmp_path / "fits_track.tif"
    source.write_bytes(b"source mask")
    tracks = {7: np.array([[0, 3, 4], [1, 6, 5], [3, 9, 7]], dtype=np.float64)}
    cache = PathDrawingCache(source, 0, 0, tracks, STYLE)
    with cache.storage() as path:
        prepared = prepare_paths(tracks, color_for=lambda _: QColor("red"),
                                 thickness=2, show_markers=True, marker_size=3, frame_path=path)
        assert prepared is not None
        cache.save(prepared, path)
    return source, tracks, cache, prepared


def test_disk_drawing_reopens_all_frames_without_rendering(tmp_path):
    source, tracks, cache, prepared = drawing(tmp_path)
    reopened = PathDrawingCache(source, 0, 0, tracks, STYLE).load()
    assert reopened is not None
    assert not reopened.frames.flags.writeable
    assert reopened.bounds == prepared.bounds
    for frame in (0, 1, 2, 3):
        assert reopened.image(frame) == prepared.image(frame)
    assert reopened.full_image == prepared.full_image
    assert not list(cache.directory.glob("*.pending"))


def test_drawing_cache_changes_with_source_edits_filter_channel_and_style(tmp_path):
    source, tracks, cache, _ = drawing(tmp_path)
    variants = [
        PathDrawingCache(source, 1, 0, tracks, STYLE),
        PathDrawingCache(source, 0, 1, tracks, STYLE),
        PathDrawingCache(source, 0, 0, {}, STYLE),
        PathDrawingCache(source, 0, 0, {7: tracks[7] + [0, 1, 0]}, STYLE),
        PathDrawingCache(source, 0, 0, tracks, {**STYLE, "thickness": 4}),
    ]
    source.write_bytes(b"a changed mask")
    variants.append(PathDrawingCache(source, 0, 0, tracks, STYLE))
    for variant in variants:
        assert variant.data_path != cache.data_path
        assert variant.load() is None


@pytest.mark.parametrize("corruption", ["metadata", "size", "missing"])
def test_broken_disk_drawing_is_ignored(tmp_path, corruption):
    _, _, cache, _ = drawing(tmp_path)
    if corruption == "metadata":
        cache.metadata_path.write_text(json.dumps({"shape": [1, 2, 3, 4]}))
    elif corruption == "size":
        cache.data_path.write_bytes(b"truncated")
    else:
        cache.data_path.unlink()
    assert cache.load() is None


def test_partial_drawing_is_removed_and_not_reused(tmp_path):
    source = tmp_path / "fits_track.tif"
    source.touch()
    tracks = {7: np.array([[0, 1, 1]], dtype=np.float64)}
    cache = PathDrawingCache(source, 0, 0, tracks, STYLE)
    with cache.storage() as path:
        prepared = prepare_paths(tracks, color_for=lambda _: QColor("red"),
                                 thickness=2, show_markers=False, marker_size=3,
                                 frame_path=path, cancelled=lambda: True)
        assert prepared is None
    assert cache.load() is None
    assert not list(cache.directory.iterdir())


@pytest.mark.parametrize("limit", ["CACHE_ENTRIES", "CACHE_BYTES"])
def test_disk_cache_keeps_latest_drawing_when_pruning(tmp_path, monkeypatch, limit):
    import fits.gui.viewer.tracking.path_cache as module
    source, tracks, old, _ = drawing(tmp_path)
    monkeypatch.setattr(module, limit, 1)
    latest = PathDrawingCache(source, 0, 0, tracks, {**STYLE, "thickness": 4})
    with latest.storage() as path:
        prepared = prepare_paths(tracks, color_for=lambda _: QColor("red"),
                                 thickness=4, show_markers=True, marker_size=3, frame_path=path)
        assert prepared is not None
        latest.save(prepared, path)
    assert latest.load() is not None
    assert old.load() is None


def test_read_only_cache_can_still_be_loaded(tmp_path, monkeypatch):
    from pathlib import Path

    _, _, cache, _ = drawing(tmp_path)
    touch = Path.touch

    def readonly(path, *args, **kwargs):
        if path == cache.metadata_path:
            raise PermissionError("read only")
        return touch(path, *args, **kwargs)

    monkeypatch.setattr(Path, "touch", readonly)
    assert cache.load() is not None


def test_unwritable_cache_directory_uses_temporary_storage(tmp_path, monkeypatch):
    from pathlib import Path

    source = tmp_path / "fits_track.tif"
    source.touch()
    cache = PathDrawingCache(source, 0, 0, {}, STYLE)
    mkdir = Path.mkdir

    def readonly(path, *args, **kwargs):
        if path == cache.directory:
            raise PermissionError("read only")
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", readonly)
    with cache.storage() as path:
        assert path is None
