"""Temporary, memory-mapped profile planes reused across selection changes."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray


class ProfilePlaneCache:
    """
    Retain one source/channel/axis context without keeping its full stack in RAM.
    """

    def __init__(self) -> None:
        """
        Allocate files lazily, only when a profile requests image planes.
        """
        self._directory: TemporaryDirectory[str] | None = None
        self._key: tuple = ()
        self._background_key: tuple | None = None
        self._original: NDArray[Any] | None = None
        self._processed: NDArray[Any] | None = None
        self._original_ready = np.zeros(0, dtype=bool)
        self._processed_ready = np.zeros(0, dtype=bool)

    def prepare(self, key: tuple, count: int, background_key: tuple | None) -> None:
        """
        Preserve original planes across settings changes and invalidate processed data.
        """
        if key != self._key:
            self.close()
            self._key = key
            self._original_ready = np.zeros(count, dtype=bool)
            self._processed_ready = np.zeros(count, dtype=bool)
        if background_key != self._background_key:
            self._background_key = background_key
            self._processed_ready[:] = False

    def get(self, index: int, *, processed: bool = False) -> NDArray[Any] | None:
        """
        Return a prepared plane view without file decoding or background subtraction.
        """
        array = self._processed if processed else self._original
        ready = self._processed_ready if processed else self._original_ready
        return array[index] if array is not None and ready[index] else None

    def put(self, index: int, image: NDArray[Any], *, processed: bool = False) -> NDArray[Any]:
        """
        Store one plane in a temporary mapped file and mark only that plane ready.
        """
        array = self._processed if processed else self._original
        ready = self._processed_ready if processed else self._original_ready
        if array is None:
            if self._directory is None:
                self._directory = TemporaryDirectory(prefix="fits-intensity-profile-")
            name = "processed.npy" if processed else "original.npy"
            array = np.lib.format.open_memmap(Path(self._directory.name) / name, mode="w+",
                                             dtype=image.dtype, shape=(len(ready), *image.shape))
            if processed:
                self._processed = array
            else:
                self._original = array
        array[index] = image
        ready[index] = True
        return array[index]

    def close(self) -> None:
        """
        Release mapped files after workers stop; source images are never modified.
        """
        for array in (self._original, self._processed):
            if isinstance(array, np.memmap):
                cast(Any, array)._mmap.close()
        self._original = self._processed = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        self._key = ()
        self._background_key = None
        self._original_ready = np.zeros(0, dtype=bool)
        self._processed_ready = np.zeros(0, dtype=bool)
