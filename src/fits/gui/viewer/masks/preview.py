"""Background preparation of disk-cached propagation sequences."""

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot

from fits.interaction.mask_preview import PreviewCancelled
from fits.tasks.reference_mask import ReferenceMaskSession
from fits.tasks.roi_mask import RoiSession


class MaskPreviewWorker(QObject):
    ready = Signal(object)
    plane_ready = Signal(object, int)
    progress = Signal(str)
    failed = Signal(str)
    done = Signal()

    def __init__(self, session: ReferenceMaskSession | RoiSession, key: tuple,
                 axis: str, options: Mapping[str, Any]) -> None:
        super().__init__()
        self.session, self.key, self.axis = session, key, axis
        self.options = dict(options)
        self.position = int(self.options["frame_index" if axis == "T" else "z_index"])

    @Slot()
    def run(self) -> None:
        def cancelled() -> bool:
            return (QThread.currentThread().isInterruptionRequested()
                    or self.session.preview_key(self.axis, **self.options) != self.key)
        try:
            if cancelled():
                return
            self.session.prepare_preview(
                self.axis, **self.options, cancelled=cancelled, progress=self.progress.emit,
                priority=lambda: self.position,
                ready=lambda index: self.plane_ready.emit(self.key, index))
            if not cancelled():
                self.ready.emit(self.key)
        except PreviewCancelled:
            pass
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self.done.emit()
