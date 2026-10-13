"""Persist completed trajectory drawings; partial drawings are never reused."""
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from fits.gui.viewer.tracking.path_item import PreparedPaths


logger = logging.getLogger(__name__)
CACHE_BYTES = 2 * 1024 ** 3
CACHE_ENTRIES = 4


class PathDrawingCache:
    def __init__(self, source: Path, channel: int, z: int,
                 tracks: dict[int, NDArray[np.float64]], style: dict[str, Any]) -> None:
        stat = source.stat()
        settings = [1, source.name, stat.st_size, stat.st_mtime_ns,
                    stat.st_ctime_ns, channel, z, style]
        digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode())
        # Coordinates identify filtered selections and unsaved manual edits too.
        for track, points in tracks.items():
            digest.update(f"{track}:{len(points)};".encode())
            digest.update(np.ascontiguousarray(points, dtype=np.float64).tobytes())
        self.directory = source.parent / ".fits" / "viewer_cache" / "tracking_paths"
        self.data_path = self.directory / f"{source.name}-{digest.hexdigest()[:24]}.rgba"
        self.metadata_path = self.data_path.with_suffix(".json")
        self.tracks = tracks

    def load(self) -> PreparedPaths | None:
        try:
            metadata = json.loads(self.metadata_path.read_text())
            shape = tuple(metadata["shape"])
            bounds = QRectF(*metadata["bounds"])
            frame_count = max((int(points[-1, 0]) + 1 for points in self.tracks.values()
                               if len(points)), default=0)
            if (len(shape) != 4 or any(type(size) is not int or size <= 0 for size in shape)
                    or shape != (frame_count, int(bounds.height()), int(bounds.width()), 4)
                    or not np.isfinite(metadata["bounds"]).all()
                    or self.data_path.stat().st_size != int(np.prod(shape, dtype=np.int64))):
                return None
            frames = np.memmap(self.data_path, mode="r", dtype=np.uint8, shape=shape)
            prepared = PreparedPaths(self.tracks, bounds, QImage(), frames)
            prepared.full_image = prepared.image(frame_count - 1)
            try:
                self.metadata_path.touch()
            except OSError:
                pass  # A readable cache still works in a read-only experiment.
            return prepared
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return None

    @contextmanager
    def storage(self) -> Iterator[Path | None]:
        """Draw directly into a pending cache file, with a temporary fallback."""
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.directory, suffix=".pending", delete=False) as file:
                temporary = Path(file.name)
        except OSError:
            logger.debug("Trajectory disk cache unavailable for %s", self.directory, exc_info=True)
        try:
            yield temporary
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.debug("Cannot remove pending trajectory cache %s", temporary)

    def save(self, prepared: PreparedPaths, temporary: Path | None) -> None:
        if temporary is None or prepared.frames is None:
            return
        metadata_temp = None
        try:
            if isinstance(prepared.frames, np.memmap):
                prepared.frames.flush()
            bounds = prepared.bounds
            metadata = {"shape": prepared.frames.shape,
                        "bounds": [bounds.x(), bounds.y(), bounds.width(), bounds.height()]}
            with NamedTemporaryFile(mode="w", dir=self.directory, suffix=".pending",
                                    delete=False) as file:
                metadata_temp = Path(file.name)
                json.dump(metadata, file)
            temporary.replace(self.data_path)
            metadata_temp.replace(self.metadata_path)
            self._prune()
        except OSError:
            logger.debug("Cannot save trajectory cache %s", self.data_path, exc_info=True)
        finally:
            if metadata_temp is not None:
                try:
                    metadata_temp.unlink(missing_ok=True)
                except OSError:
                    logger.debug("Cannot remove pending trajectory metadata %s", metadata_temp)

    def _prune(self) -> None:
        """Retain recent drawings, always keeping the drawing just completed."""
        entries = sorted(self.directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
        sizes = {path: path.with_suffix(".rgba").stat().st_size
                 for path in entries if path.with_suffix(".rgba").exists()}
        total = sum(sizes.values())
        count = len(sizes)
        for path in entries:
            if total <= CACHE_BYTES and count <= CACHE_ENTRIES:
                break
            if path == self.metadata_path:
                continue
            path.unlink(missing_ok=True)
            path.with_suffix(".rgba").unlink(missing_ok=True)
            total -= sizes.get(path, 0)
            if path in sizes:
                count -= 1
