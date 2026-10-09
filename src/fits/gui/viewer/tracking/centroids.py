"""Thread-safe, frame-local centroid caching for interactive tracking."""
from collections.abc import Callable, Iterable
from collections import OrderedDict
from threading import RLock
from pathlib import Path
from tempfile import NamedTemporaryFile
import json
import logging
from zipfile import BadZipFile

import numpy as np
from numpy.typing import NDArray

from fits.gui.viewer.tracking.trajectories import calculate_track_centroids


logger = logging.getLogger(__name__)


def _signature(source: Path) -> str:
    stat = source.stat()
    return json.dumps([1, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])


def _cache_path(source: Path, channel: int, z: int) -> Path:
    return source.parent / ".fits" / "viewer_cache" / f"{source.name}.centroids-c{channel}-z{z}.npz"


def _track_lengths(tracks: dict[int, NDArray[np.float64]]) -> dict[int, int]:
    """Inclusive frame spans, including gaps, consistent with extraction."""
    return {track: int(points[:, 0].max() - points[:, 0].min()) + 1
            for track, points in tracks.items() if len(points)}


def _load(source: Path, channel: int, z: int, count: int,
          ) -> tuple[dict[int, NDArray[np.float64]], dict[int, int]] | None:
    try:
        target = _cache_path(source, channel, z)
        legacy = source.with_name(f".{source.name}.centroids-c{channel}-z{z}.npz")
        path = target if target.exists() else legacy
        with np.load(path, allow_pickle=False) as saved:
            signature = str(saved["signature"])
            if signature != _signature(source):
                return None
            ids, points = saved["ids"], saved["points"]
            if (ids.ndim != 1 or points.shape != (len(ids), 3)
                    or not np.issubdtype(ids.dtype, np.integer) or np.any(ids <= 0)
                    or not np.isfinite(points).all()
                    or np.any(points[:, 0] < 0) or np.any(points[:, 0] >= count)
                    or np.any(points[:, 0] != np.floor(points[:, 0]))):
                return None
            boundaries = np.flatnonzero(ids[1:] != ids[:-1]) + 1
            starts = np.concatenate(([0], boundaries)) if len(ids) else np.empty(0, dtype=int)
            stops = np.concatenate((boundaries, [len(ids)])) if len(ids) else np.empty(0, dtype=int)
            result = {int(ids[start]): points[start:stop] for start, stop in zip(starts, stops, strict=True)}
            if len(result) != len(starts):
                return None
            if "track_ids" in saved and "track_lengths" in saved:
                track_ids, lengths = saved["track_ids"], saved["track_lengths"]
                if (track_ids.shape != (len(result),) or lengths.shape != track_ids.shape
                        or not np.issubdtype(track_ids.dtype, np.integer)
                        or not np.issubdtype(lengths.dtype, np.integer)
                        or len(set(track_ids.tolist())) != len(result)
                        or set(track_ids.tolist()) != set(result)
                        or np.any(lengths < 1) or np.any(lengths > count)):
                    return None
                track_lengths = {int(track): int(length)
                                 for track, length in zip(track_ids, lengths, strict=True)}
            else:
                track_lengths = _track_lengths(result)
        if path == legacy:
            if _save(source, channel, z, signature, result, track_lengths):
                try:
                    legacy.unlink(missing_ok=True)
                except OSError:
                    pass
        return result, track_lengths
    except (OSError, ValueError, TypeError, KeyError, EOFError, BadZipFile):
        return None


def _save(source: Path, channel: int, z: int, signature: str,
          tracks: dict[int, NDArray[np.float64]], lengths: dict[int, int]) -> bool:
    temporary: Path | None = None
    try:
        if _signature(source) != signature:
            return False
        target = _cache_path(source, channel, z)
        target.parent.mkdir(parents=True, exist_ok=True)
        ids = np.concatenate([np.full(len(points), track, dtype=np.int64)
                              for track, points in tracks.items()]) if tracks else np.empty(0, np.int64)
        points = np.concatenate(list(tracks.values())) if tracks else np.empty((0, 3))
        with NamedTemporaryFile(dir=target.parent, prefix=target.name, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            np.savez_compressed(file, signature=signature, ids=ids, points=points,
                                track_ids=np.asarray(list(lengths), dtype=np.int64),
                                track_lengths=np.asarray(list(lengths.values()), dtype=np.int64))
        temporary.replace(target)
        return True
    except OSError:
        logger.debug("Centroid disk cache unavailable for %s", source, exc_info=True)
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class CentroidCache:
    def __init__(self) -> None:
        self.lock = RLock()
        self.revision = 0
        self.planes: dict[tuple[int, int, int], dict[int, NDArray[np.float64]]] = {}
        self.tracks: dict[tuple[int, int], dict[int, NDArray[np.float64]]] = {}
        self.lengths: dict[tuple[int, int], dict[int, int]] = {}
        self.matches: OrderedDict[tuple, frozenset[int]] = OrderedDict()

    def clear(self) -> None:
        with self.lock:
            self.revision += 1
            self.planes.clear()
            self.tracks.clear()
            self.lengths.clear()
            self.matches.clear()

    def invalidate(self, channel: int, z: int, frames: Iterable[int]) -> None:
        with self.lock:
            self.revision += 1
            self.tracks.pop((channel, z), None)
            self.lengths.pop((channel, z), None)
            self.matches = OrderedDict((key, value) for key, value in self.matches.items()
                                       if key[:2] != (channel, z))
            for frame in frames:
                self.planes.pop((frame, channel, z), None)

    def cached(self, channel: int, z: int) -> dict[int, NDArray[np.float64]] | None:
        with self.lock:
            return self.tracks.get((channel, z))

    def remove_label(self, channel: int, z: int, label: int,
                     frames: Iterable[int]) -> None:
        """Update known coordinates after deletion without scanning mask pixels."""
        removed_frames = frozenset(frames)
        with self.lock:
            self.revision += 1
            for frame in removed_frames:
                key = frame, channel, z
                if key in self.planes:
                    self.planes[key] = {
                        track: points for track, points in self.planes[key].items()
                        if track != label}
            key = channel, z
            if key in self.tracks:
                tracks = dict(self.tracks[key])
                points = tracks.get(label)
                if points is not None:
                    remaining = points[~np.isin(points[:, 0], tuple(removed_frames))]
                    if len(remaining):
                        tracks[label] = remaining
                    else:
                        tracks.pop(label)
                self.tracks[key] = tracks
                self.lengths[key] = _track_lengths(tracks)
            self.matches = OrderedDict((key, value) for key, value in self.matches.items()
                                       if key[:2] != (channel, z))

    def matching(self, channel: int, z: int, operator: str, value: int,
                 maximum: int | None = None) -> frozenset[int]:
        """Reuse lengths and recent filter results without rescanning observations."""
        comparisons: dict[str, Callable[[int], bool]] = {
            "lt": lambda length: length < value,
            "le": lambda length: length <= value,
            "eq": lambda length: length == value,
            "ne": lambda length: length != value,
            "ge": lambda length: length >= value,
            "gt": lambda length: length > value,
            "between": lambda length: maximum is not None and value <= length <= maximum,
        }
        if operator not in comparisons:
            raise ValueError(f"Unknown track-length comparison: {operator!r}.")
        if operator == "between" and (maximum is None or maximum < value):
            raise ValueError("The maximum track length must be at least the minimum.")
        key = channel, z, operator, value, maximum if operator == "between" else None
        with self.lock:
            cached = self.matches.get(key)
            if cached is not None:
                self.matches.move_to_end(key)
                return cached
            comparison = comparisons[operator]
            result = frozenset(track for track, length in self.lengths[channel, z].items()
                               if comparison(length))
            self.matches[key] = result
            while len(self.matches) > 16:
                self.matches.popitem(last=False)
            return result

    def calculate(self, read: Callable[[int, int, int], NDArray], *, count: int,
                  channel: int, z: int, source: Path | None = None,
                  progress: Callable[[int, int], None] | None = None,
                  cancelled: Callable[[], bool] | None = None,
                  ) -> dict[int, NDArray[np.float64]] | None:
        cached = self.cached(channel, z)
        if cached is not None:
            return cached
        with self.lock:
            revision = self.revision
        signature = None
        if source is not None and revision == 0:
            try:
                signature = _signature(source)
            except OSError:
                pass
            saved = _load(source, channel, z, count) if signature is not None else None
            if saved is not None:
                saved_tracks, saved_lengths = saved
                planes: dict[tuple[int, int, int], dict[int, NDArray[np.float64]]] = {
                    (frame, channel, z): {} for frame in range(count)}
                for track, points in saved_tracks.items():
                    if cancelled is not None and cancelled():
                        return None
                    for point in points:
                        planes[int(point[0]), channel, z][track] = point.reshape(1, 3)
                with self.lock:
                    if revision != self.revision:
                        return None
                    self.planes.update(planes)
                    self.tracks[channel, z] = saved_tracks
                    self.lengths[channel, z] = saved_lengths
                if progress is not None:
                    progress(count, count)
                return saved_tracks
        observations: dict[int, list[NDArray[np.float64]]] = {}
        for frame in range(count):
            if cancelled is not None and cancelled():
                return None
            key = frame, channel, z
            with self.lock:
                if revision != self.revision:
                    return None
                plane = self.planes.get(key)
            if plane is None:
                # A single frame uses the same centroid definition as exports.
                plane = calculate_track_centroids(
                    lambda _frame, c, depth: read(frame, c, depth),
                    frame_count=1, channel_index=channel, z_index=z)
                for points in plane.values():
                    points[:, 0] = frame
                with self.lock:
                    if revision != self.revision:
                        return None
                    self.planes[key] = plane
            for track, points in plane.items():
                observations.setdefault(track, []).append(points)
            if progress is not None:
                progress(frame + 1, count)
        result = {track: np.concatenate(points) for track, points in observations.items()}
        lengths = _track_lengths(result)
        with self.lock:
            if revision != self.revision:
                return None
            self.tracks[channel, z] = result
            self.lengths[channel, z] = lengths
        if source is not None and signature is not None:
            _save(source, channel, z, signature, result, lengths)
        return result
