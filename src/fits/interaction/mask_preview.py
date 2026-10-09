"""Temporary disk-backed propagation previews for one independent sequence."""

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

import numpy as np
from numpy.typing import NDArray


class PreviewCancelled(Exception):
    """The requested preview was superseded before it was completed."""


class MaskPreviewCache:
    """Keep one completed sequence per drawing session, outside source masks."""

    def __init__(self, source: Path) -> None:
        self.source = source
        self.key: tuple | None = None
        self._array: NDArray[np.uint8] | None = None
        self._directory: TemporaryDirectory | None = None
        self._lock = RLock()
        self._ready: NDArray[np.bool_] | None = None

    def contains(self, key: tuple) -> bool:
        with self._lock:
            return (self.key == key and self._array is not None
                    and (self._ready is None or bool(np.all(self._ready))))

    def cached_plane(self, key: tuple, index: int) -> NDArray[np.uint8] | None:
        """Read a completed plane without ever starting work on the GUI thread."""
        with self._lock:
            if self.key != key or self._array is None:
                return None
            if self._ready is not None and not self._ready[index]:
                return None
            return self._array[index].copy()

    def copy_into(self, key: tuple, output: NDArray[np.uint8]) -> bool:
        """Copy a matching completed sequence to save storage without recomputing."""
        with self._lock:
            if self.key != key or self._array is None:
                return False
            if self._ready is not None and not np.all(self._ready):
                return False
            for index in range(len(self._array)):
                output[index] = self._array[index]
            return True

    def close(self) -> None:
        with self._lock:
            self.key = None
            self._ready = None
            self._array = None
            if self._directory is not None:
                self._directory.cleanup()
                self._directory = None

    def prepare(self, key: tuple, *, count: int, shape: tuple[int, int],
                read: Callable[[int], NDArray],
                prepare: Callable[[NDArray[np.uint8]], Callable[[int], NDArray]],
                priority: Callable[[], int], cancelled: Callable[[], bool],
                ready: Callable[[int], None], progress: Callable[[str], None]) -> None:
        """Publish planes progressively, following the user's current position."""
        def check() -> None:
            if cancelled():
                raise PreviewCancelled()
        check()
        if self.contains(key):
            return
        parent = self.source.parent / ".fits" / "viewer_cache"
        try:
            parent.mkdir(parents=True, exist_ok=True)
            directory = TemporaryDirectory(prefix="mask-preview-", dir=parent)
        except OSError:
            directory = TemporaryDirectory(prefix="fits-mask-preview-")
        anchors = output = build = result = None
        published = False
        try:
            anchor_path = Path(directory.name) / "anchors.npy"
            anchors = np.lib.format.open_memmap(
                anchor_path, mode="w+", dtype=np.uint8, shape=(count, *shape))
            progress("Reading propagation anchors")
            for index in range(count):
                check()
                anchors[index] = read(index)
            check()
            build = prepare(anchors)
            check()
            output = np.lib.format.open_memmap(
                Path(directory.name) / "preview.npy", mode="w+", dtype=np.uint8,
                shape=(count, *shape))
            available = np.zeros(count, dtype=bool)
            with self._lock:
                self.close()
                self.key, self._array, self._directory = key, output, directory
                self._ready = available
                published = True
            remaining = set(range(count))
            while remaining:
                check()
                center = priority()
                index = min(remaining, key=lambda position: (abs(position - center), position))
                result = build(index)
                check()
                with self._lock:
                    output[index] = result
                    available[index] = True
                remaining.remove(index)
                progress(f"Preparing preview: {count - len(remaining)}/{count} planes")
                ready(index)
            output.flush()
            build = anchors = result = None
            anchor_path.unlink()
        except BaseException:
            build = anchors = output = result = None
            if published:
                with self._lock:
                    if self.key == key:
                        self.close()
            else:
                directory.cleanup()
            raise

    def plane(self, key: tuple, index: int, *, count: int,
              shape: tuple[int, int], read: Callable[[int], NDArray],
              complete: Callable[[NDArray[np.uint8]], NDArray[np.uint8]],
              cancelled: Callable[[], bool] | None = None,
              progress: Callable[[str], None] | None = None) -> NDArray[np.uint8]:
        """Build once, then read cached planes; callers serialize builds/cleanup."""
        def check() -> None:
            if cancelled is not None and cancelled():
                raise PreviewCancelled()
        check()
        if not 0 <= index < count:
            raise IndexError("Preview plane index is outside the sequence.")
        if self.contains(key):
            assert self._array is not None
            return self._array[index].copy()
        parent = self.source.parent / ".fits" / "viewer_cache"
        anchors = completed = output = None
        try:
            parent.mkdir(parents=True, exist_ok=True)
            directory = TemporaryDirectory(prefix="mask-preview-", dir=parent)
        except OSError:
            directory = TemporaryDirectory(prefix="fits-mask-preview-")
        try:
            anchor_path = Path(directory.name) / "anchors.npy"
            anchors = np.lib.format.open_memmap(
                anchor_path, mode="w+", dtype=np.uint8, shape=(count, *shape))
            if progress is not None:
                progress("Reading propagation anchors")
            for plane in range(count):
                check()
                anchors[plane] = read(plane)
            check()
            if progress is not None:
                progress("Interpolating propagation preview")
            completed = complete(anchors) if np.any(anchors) else anchors
            check()
            output = np.lib.format.open_memmap(
                Path(directory.name) / "preview.npy", mode="w+", dtype=np.uint8,
                shape=(count, *shape))
            if progress is not None:
                progress("Caching propagation preview")
            for plane in range(count):
                check()
                output[plane] = completed[plane]
            output.flush()
            check()
            completed = anchors = None
            anchor_path.unlink()
            with self._lock:
                self.close()
                self._directory, self._array, self.key = directory, output, key
            return output[index].copy()
        except BaseException:
            # Release local mappings before removing their files on Windows.
            output = completed = anchors = None
            directory.cleanup()
            raise
