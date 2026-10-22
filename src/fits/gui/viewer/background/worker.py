"""Single requested background-subtraction plane outside the GUI thread."""

from time import perf_counter

from numpy.typing import NDArray
from PySide6.QtCore import QObject, QThread, Signal

from fits.settings.models import BGSubSettings
from fits.tasks.bg_sub_tuning import BackgroundTuningSession


class BackgroundPreviewWorker(QThread):
    """Process one immutable request; navigation can select the next request meanwhile."""

    ready = Signal(float)
    failed = Signal(str)

    def __init__(self, session: BackgroundTuningSession, image: NDArray,
                 settings: BGSubSettings, frame: int, channel: str, z: int,
                 parent: QObject | None = None) -> None:
        """Capture the selected source plane and a snapshot of its settings."""
        super().__init__(parent)
        self.session, self.image, self.settings = session, image, settings
        self.frame, self.channel, self.z = frame, channel, z

    def run(self) -> None:
        """Compute exactly one plane and report its elapsed processing time."""
        try:
            started = perf_counter()
            self.session.compute_plane(self.image, self.settings, self.frame, self.channel, self.z)
            self.ready.emit(perf_counter() - started)
        except Exception as error:
            self.failed.emit(str(error))
