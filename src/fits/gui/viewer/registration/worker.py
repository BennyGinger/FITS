"""One cancellable registration preview outside the GUI thread."""

from PySide6.QtCore import QObject, QThread, Signal, Slot

from fits.settings.models import RegisterTimeSettings
from fits.tasks.registration.tuned import Mode, RegistrationSettings
from fits.tasks.registration.tuning import RegistrationTuningSession


class RegistrationPreviewWorker(QObject):
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int)
    done = Signal()

    def __init__(self, session: RegistrationTuningSession, mode: Mode,
                 settings: RegistrationSettings, upstream: RegisterTimeSettings | None) -> None:
        super().__init__()
        self.session = session
        self.mode: Mode = mode
        self.settings = settings
        self.upstream = upstream

    @Slot()
    def run(self) -> None:
        try:
            result = self.session.run_preview(
                self.mode, self.settings, upstream=self.upstream,
                cancelled=lambda: QThread.currentThread().isInterruptionRequested(),
                progress=self.progress.emit)
            self.ready.emit(result)
        except InterruptedError:
            pass
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self.done.emit()
