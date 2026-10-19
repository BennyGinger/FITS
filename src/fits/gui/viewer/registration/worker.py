"""One cancellable registration preview outside the GUI thread."""

from PySide6.QtCore import QObject, QThread, Signal, Slot

from fits.interaction.crop import CropBounds
from fits.tasks.registration.tuned import Mode, RegistrationSettings
from fits.tasks.registration.tuning import RegistrationTuningSession


class RegistrationPreviewWorker(QObject):
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int)
    done = Signal()

    def __init__(self, session: RegistrationTuningSession, mode: Mode,
                 settings: RegistrationSettings, *,
                 crop: CropBounds | None = None) -> None:
        """Capture settings and enabled fitting crops for a background fit."""
        super().__init__()
        self.session = session
        self.mode: Mode = mode
        self.settings = settings
        self.crop = crop

    @Slot()
    def run(self) -> None:
        """Fit transforms with cancellation; displayed planes are applied on demand."""
        try:
            result = self.session.run_preview(
                self.mode, self.settings, crop=self.crop,
                cancelled=lambda: QThread.currentThread().isInterruptionRequested(),
                progress=self.progress.emit)
            self.ready.emit(result)
        except InterruptedError:
            pass
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self.done.emit()
