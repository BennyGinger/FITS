"""Bounded plane reading and disk-backed mask edits for interactive viewers."""

from collections import OrderedDict
from collections.abc import Callable, Iterator
from itertools import product
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory, TemporaryFile
from threading import RLock
from typing import Any

import numpy as np
from fits_io import FitsIO
from numpy.typing import NDArray


def disk_copy(array: NDArray, dtype: Any = None) -> NDArray:
    """Copy a plane or stack to temporary mapped storage in YX-sized chunks."""
    with TemporaryFile() as file:
        output = np.memmap(file, dtype=array.dtype if dtype is None else dtype,
                           mode="w+", shape=array.shape)
    for index in np.ndindex(array.shape[:-2]):
        output[index] = array[index]
    return output


def aligned_mask_store(reader: FitsIO, *, source_axes: str,
                       source_shape: tuple[int, ...],
                       source_channels: tuple[str, ...],
                       transform: Callable[[NDArray], NDArray]) -> "PlaneStore":
    """Map compact artifact channels onto their source image without reading pixels."""
    channels = tuple(reader.channel_labels)
    expected = tuple(size for axis, size in zip(source_axes, source_shape, strict=True)
                     if axis != "C")
    actual = tuple(size for axis, size in zip(reader.axes, reader.reader.shape, strict=True)
                   if axis != "C")
    if reader.axes.replace("C", "") != source_axes.replace("C", "") or actual != expected:
        raise ValueError("Mask axes and shape must match the source outside channels.")
    channel_count = reader.reader.shape[reader.axes.index("C")] if "C" in reader.axes else 1
    if len(channels) != channel_count or len(set(channels)) != len(channels):
        raise ValueError("Mask channel labels do not match its channel axis.")
    for channel in channels:
        if channel not in source_channels:
            raise ValueError(f"Mask channel {channel!r} is not present in the source.")
    mapping = tuple(channels.index(label) if label in channels else None
                    for label in source_channels)
    return PlaneStore(source_axes, source_shape, reader=reader, dtype=np.uint8,
                      channel_map=mapping, transform=transform)


class PlaneStore:
    """Read immutable source planes on demand; keep edited planes on disk."""

    def __init__(self, axes: str, shape: tuple[int, ...], *,
                 reader: FitsIO | None = None, dtype: Any = None,
                 channel_map: tuple[int | None, ...] | None = None,
                 transform: Callable[[NDArray], NDArray] | None = None,
                 cache_bytes: int = 64 * 1024 * 1024,
                 cache_planes: int = 8) -> None:
        if len(axes) != len(shape) or "".join(a for a in axes if a not in "TCZ") != "YX":
            raise ValueError(f"A plane store requires TCZ navigation and YX, got {axes!r}, {shape}.")
        self.axes = axes
        self.shape = tuple(shape)
        self.ndim = len(shape)
        self.reader = reader
        self.dtype = np.dtype(dtype) if dtype is not None else None
        self.channel_map = channel_map
        self.transform = transform
        self.cache_bytes = cache_bytes
        self.cache_planes = cache_planes
        self._cache: OrderedDict[tuple[int, int, int], NDArray] = OrderedDict()
        self._cache_size = 0
        self._edits: dict[tuple[int, int, int], Path] = {}
        self._temporary: TemporaryDirectory | None = None
        self._lock = RLock()

    def axis_size(self, axis: str) -> int:
        return self.shape[self.axes.index(axis)] if axis in self.axes else 1

    def keys(self) -> Iterator[tuple[int, int, int]]:
        return product(range(self.axis_size("T")), range(self.axis_size("C")),
                       range(self.axis_size("Z")))

    def selection(self, key: tuple[int, int, int]) -> tuple[int | slice, ...]:
        positions = dict(zip("TCZ", key, strict=True))
        for axis, index in positions.items():
            if not 0 <= index < self.axis_size(axis):
                raise IndexError(f"{axis} index {index} is outside the artifact.")
        return tuple(positions.get(axis, slice(None)) for axis in self.axes)

    def plane(self, frame: int = 0, channel: int = 0, z: int = 0) -> NDArray:
        key = frame, channel, z
        self.selection(key)
        with self._lock:
            if key in self._edits:
                return np.load(self._edits[key], mmap_mode="r")
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            source_channel = channel if self.channel_map is None else self.channel_map[channel]
            if self.reader is None or source_channel is None:
                array = np.zeros((self.axis_size("Y"), self.axis_size("X")),
                                 dtype=self.dtype)
            else:
                array = np.asarray(self.reader.get_plane(frame, source_channel, z).array)
                if self.transform is not None:
                    array = self.transform(array)
                if self.dtype is not None:
                    array = array.astype(self.dtype, copy=False)
            if array.shape != (self.axis_size("Y"), self.axis_size("X")):
                raise ValueError("Loaded plane does not match the artifact's YX shape.")
            array.setflags(write=False)
            if array.nbytes <= self.cache_bytes:
                self._cache[key] = array
                self._cache_size += array.nbytes
                while (self._cache_size > self.cache_bytes
                       or len(self._cache) > self.cache_planes):
                    _, removed = self._cache.popitem(last=False)
                    self._cache_size -= removed.nbytes
            return array

    def _temporary_path(self, name: str) -> Path:
        if self._temporary is None:
            self._temporary = TemporaryDirectory(prefix="fits-viewer-")
        return Path(self._temporary.name) / name

    def writable_plane(self, frame: int = 0, channel: int = 0, z: int = 0) -> NDArray:
        key = frame, channel, z
        with self._lock:
            if key not in self._edits:
                current = self.plane(*key)
                path = self._temporary_path(f"{frame}-{channel}-{z}.npy")
                np.save(path, current)
                self._edits[key] = path
                cached = self._cache.pop(key, None)
                if cached is not None:
                    self._cache_size -= cached.nbytes
            return np.load(self._edits[key], mmap_mode="r+")

    def set_plane(self, key: tuple[int, int, int], array: NDArray) -> None:
        self.writable_plane(*key)[...] = array

    def copy(self, channel: int | None = None) -> NDArray:
        """Assemble a disk-backed array for existing save/interpolation APIs."""
        axes = self.axes if channel is None else self.axes.replace("C", "")
        shape = tuple(self.axis_size(axis) for axis in axes)
        dtype = self.dtype if self.dtype is not None else self.plane().dtype
        # The mapping owns its storage after the temporary file handle closes.
        with TemporaryFile() as file:
            output = np.memmap(file, dtype=dtype, mode="w+", shape=shape)
        for key in self.keys():
            if channel is not None and key[1] != channel:
                continue
            positions = dict(zip("TCZ", key, strict=True))
            output[tuple(positions.get(axis, slice(None)) for axis in axes)] = self.plane(*key)
        return output

    def preserve_source(self, output_path: Path) -> None:
        """Keep session anchors stable when Save overwrites their source mask."""
        if self.reader is None or self.reader.reader.img_path.resolve() != output_path.resolve():
            return
        with self._lock:
            snapshot = self._temporary_path("source.tif")
            copy2(output_path, snapshot)
            self.reader = FitsIO.from_path(snapshot)

    def close(self) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_size = 0
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
            self._edits.clear()
