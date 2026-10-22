"""On-demand background previews with reusable SMO and bounded plane storage."""

from collections import OrderedDict
from pathlib import Path
from threading import RLock

import numpy as np
from numpy.typing import NDArray
from bg_sub import BackgroundSubtractor

from fits.interaction import FitsImageSession
from fits.settings.models import BGSubSettings


class BackgroundTuningSession(FitsImageSession):
    """Keep only requested previews for one original experiment."""

    def __init__(self, source_path: str | Path) -> None:
        """Open a virtual input and initialize empty processor and plane caches."""
        super().__init__(source_path)
        self._processor: BackgroundSubtractor | None = None
        self._processor_key: tuple | None = None
        self._previews: OrderedDict[tuple, NDArray] = OrderedDict()
        self._lock = RLock()

    @staticmethod
    def preview_key(settings: BGSubSettings, frame: int, channel: str, z: int) -> tuple:
        """Identify numerical settings and one requested image plane."""
        return (settings.sigma, settings.size, settings.threshold, settings.statistic,
                tuple(settings.exclude_channel or ()), frame, channel, z)

    def cached_preview(self, settings: BGSubSettings, frame: int, channel: str, z: int) -> NDArray | None:
        """Return only a result matching the requested settings and coordinates."""
        key = self.preview_key(settings, frame, channel, z)
        with self._lock:
            result = self._previews.get(key)
            if result is not None:
                self._previews.move_to_end(key)
            return result

    def compute_plane(self, image: NDArray, settings: BGSubSettings,
                      frame: int, channel: str, z: int) -> NDArray:
        """Compute one requested plane; callers serialize work on this session."""
        cached = self.cached_preview(settings, frame, channel, z)
        if cached is not None:
            return cached
        if channel in (settings.exclude_channel or ()):
            result = image.astype(np.float32, copy=True)
        else:
            processor_key = image.shape, settings.sigma, settings.size
            if self._processor is None or self._processor_key != processor_key:
                self._processor = BackgroundSubtractor((image.shape[0], image.shape[1]), sigma=settings.sigma, size=settings.size)
                self._processor_key = processor_key
            result = self._processor.process(image, threshold=settings.threshold, statistic=settings.statistic)
        result.setflags(write=False)
        key = self.preview_key(settings, frame, channel, z)
        with self._lock:
            self._previews[key] = result
            # Retain one oversized current plane so it can still be displayed.
            while len(self._previews) > 1 and (len(self._previews) > 8 or
                    sum(plane.nbytes for plane in self._previews.values()) > 64 * 1024**2):
                self._previews.popitem(last=False)
        return result

    def close(self) -> None:
        """Release processed planes, the configured model and source cache."""
        self._previews.clear()
        self._processor = None
        self._processor_key = None
        super().close()
