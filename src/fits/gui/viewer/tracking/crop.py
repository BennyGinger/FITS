"""Automatic tracking crop worker and shared rectangle controls."""

from collections.abc import Callable
from typing import Any

from numpy.typing import NDArray
from PySide6.QtCore import QObject, QThread, Signal, Slot

from fits.gui.viewer.common.crop import CropPanel
from fits.gui.viewer.tracking.crop_geometry import fit_track_bounds

__all__ = ["CropFitWorker", "CropPanel"]


class CropFitWorker(QObject):
    ready = Signal(object)
    failed = Signal(object)
    done = Signal()

    def __init__(self, frame_at: Callable[[int], NDArray[Any]], count: int,
                 track_ids: tuple[int, ...], context: tuple) -> None:
        """Capture the selected tracks and immutable request context."""
        super().__init__()
        self.frame_at, self.count, self.track_ids = frame_at, count, track_ids
        self.context = context

    @Slot()
    def run(self) -> None:
        """Find track bounds outside the GUI thread with cooperative cancellation."""
        try:
            bounds = fit_track_bounds(self.frame_at, self.count, self.track_ids,
                                      QThread.currentThread().isInterruptionRequested)
            if bounds is not None:
                self.ready.emit((self.context, bounds))
        except Exception as error:
            self.failed.emit((self.context, str(error)))
        finally:
            self.done.emit()
