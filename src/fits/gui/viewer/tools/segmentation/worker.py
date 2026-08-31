from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from fits.tasks.segmentation.preview_cache import SegmentationPreview
from fits.tasks.segmentation.tuning import SegmentationTuningSession


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    frame_index: int
    channel: str
    z_index: int
    user_settings: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreviewOutcome:
    request: PreviewRequest
    preview: SegmentationPreview


class PreviewWorker(QObject):
    """
    Run one segmentation preview outside the GUI thread.
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self,
                 session: SegmentationTuningSession,
                 request: PreviewRequest,
                 ) -> None:
        super().__init__()
        self.session = session
        self.request = request

    @Slot()
    def run(self) -> None:
        try:
            preview = self.session.run_preview(
                self.request.frame_index,
                self.request.channel,
                self.request.z_index,
                self.request.user_settings,)
        except Exception as error:
            self.failed.emit(str(error))
            return
        self.finished.emit(PreviewOutcome(self.request, preview))
