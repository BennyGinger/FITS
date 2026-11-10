"""Shared drawing, intensity readout and live-profile coordination."""

from typing import Any

from numpy.typing import NDArray
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QPushButton, QWidget

from fits.gui.viewer.common.drawing_panel import DrawingPanel
from fits.gui.viewer.common.image_viewer import FitsImageViewer
from fits.gui.viewer.common.intensity_profile import IntensityProfileDialog, ProfileRequest
from fits.interaction import FitsImageSession
from fits.settings.models import BGSubSettings
from fits.tasks.bg_sub_tuning import BackgroundTuningSession


class AreaMeasurement(QObject):
    """
    Reuse one persistent selection for current means and optional live profiles.
    """

    def __init__(self, viewer: FitsImageViewer, parent: QWidget) -> None:
        """
        Create shared controls without starting any image reads or processing.
        """
        super().__init__(parent)
        self.viewer = viewer
        self.drawing = DrawingPanel()
        self.drawing.bind(viewer)
        self.profile_button = QPushButton("Show profile")
        self.profile_button.setEnabled(False)
        self.profile_button.clicked.connect(self._show_profile)
        self.dialog = IntensityProfileDialog(parent)
        self._session: FitsImageSession | None = None
        self._context: tuple = ()
        self._original: NDArray[Any] | None = None
        self._processed: NDArray[Any] | None = None
        self._background: BGSubSettings | None = None
        self._frame = self._z = self._series = 0
        self._channel = ""
        self.drawing.changed.connect(self._refresh)

    def update(self, session: FitsImageSession, image: NDArray[Any], frame: int,
               channel: str, z: int, *, series: int = 0,
               processed: NDArray[Any] | None = None, background: BGSubSettings | None = None,
               ) -> None:
        """
        Supply existing planes for means and snapshot only changed profile inputs.
        """
        if self._session is not session:
            self.reset()
            self._session = session
            self.drawing.reset((image.shape[0], image.shape[1]))
        self._original, self._processed = image, processed
        self._frame, self._channel, self._z, self._series = frame, channel, z, series
        self._background = background.model_copy(deep=True) if background is not None else None
        self._refresh()

    def _refresh(self) -> None:
        """
        Show source means and update the live profile only when its inputs change.
        """
        area, session = self.drawing.selection, self._session
        readout = self.viewer.pixel_readout
        if area is not None and self._original is not None:
            values = (("Mean", area.mean(self._original)),)
            if self._processed is not None:
                values = (("Original", values[0][1]), ("BGSub", area.mean(self._processed)))
            readout.set_measurements(values)
        else:
            readout.set_measurements(None)
        available = area is not None and session is not None and (session.frame_count > 1 or session.plane_count > 1)
        self.profile_button.setEnabled(available)
        context = (id(session), area, self._frame, self._channel, self._z, self._series, self._processed is not None,
                   BackgroundTuningSession.preview_key(self._background, 0, "", 0) if self._background is not None else None)
        if context == self._context:
            return
        self._context = context
        request = (ProfileRequest(session.source_path, self._series, self._channel, self._frame,
                                  self._z, session.frame_count, session.plane_count, area, self._background,
                                  channel_index=session.channel_labels.index(self._channel), interval=session._reader.interval,
                                  original=self._original, processed=self._processed)
                   if available and session is not None and area is not None else None)
        self.dialog.update_request(request)

    def _show_profile(self) -> None:
        """
        Open the independent plot and start computing the current request.
        """
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.refresh_now()

    def reset(self) -> None:
        """
        Release references and stop background work before changing sources.
        """
        self.dialog.stop(clear=True)
        self.dialog.hide()
        self._session = None
        self._original = self._processed = None
        self._context = ()
        self.drawing.reset()
        self.profile_button.setEnabled(False)
        self.viewer.pixel_readout.set_measurements(None)
