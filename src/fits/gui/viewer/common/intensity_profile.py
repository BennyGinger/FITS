"""Latest-selection intensity profiles computed outside the GUI thread."""

from dataclasses import dataclass, field, replace
from pathlib import Path
from time import monotonic
from typing import Any
from numpy.typing import NDArray
from typing import cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QShowEvent, QStandardItemModel
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from fits.gui.settings.wheel_widgets import FocusWheelComboBox
from fits.gui.viewer.common.area_selection import AreaSelection
from fits.gui.viewer.common.profile_cache import ProfilePlaneCache
from fits.gui.viewer.common.profile_plot import ProfilePlot
from fits.interaction import FitsImageSession
from fits.settings.models import BGSubSettings
from fits.tasks.bg_sub_tuning import BackgroundTuningSession


@dataclass(frozen=True)
class ProfileRequest:
    """
    Snapshot one source, channel, fixed plane and measurement geometry.
    """

    source: Path
    series: int
    channel: str
    frame: int
    z: int
    frames: int
    planes: int
    area: AreaSelection
    background: BGSubSettings | None = None
    axis: str = "T"
    channel_index: int = 0
    interval: float | None = None
    original: NDArray[Any] | None = field(default=None, compare=False, repr=False)
    processed: NDArray[Any] | None = field(default=None, compare=False, repr=False)


class ProfileWorker(QThread):
    """
    Read one plane at a time using an independent source and bounded caches.
    """

    ready = Signal(object, object)
    failed = Signal(str)

    def __init__(self, request: ProfileRequest, parent: QWidget, cache: ProfilePlaneCache | None = None) -> None:
        """
        Capture immutable settings before starting numerical work.
        """
        super().__init__(parent)
        self.request = request
        self.cache = cache if cache is not None else ProfilePlaneCache()
        self._own_cache = cache is None

    def run(self) -> None:
        """
        Publish original means first, then reuse or prepare processed planes progressively.
        """
        request = self.request
        session: FitsImageSession | None = None
        count = request.frames if request.axis == "T" else request.planes
        fixed = request.z if request.axis == "T" else request.frame
        background_key = (BackgroundTuningSession.preview_key(request.background, 0, "", 0)
                          if request.background is not None else None)
        current = request.frame if request.axis == "T" else request.z
        try:
            self.cache.prepare((request.source, request.series, request.channel_index, request.axis, fixed, count),
                               count, background_key)
            if request.original is not None:
                self.cache.put(current, request.original)
            if request.processed is not None and request.background is not None:
                self.cache.put(current, request.processed, processed=True)
            original, processed = [], []
            pixels = None
            coordinates = (np.arange(count) * request.interval
                           if request.axis == "T" and request.interval is not None and request.interval > 0
                           else np.arange(1, count + 1))
            for index in range(count):
                if self.isInterruptionRequested():
                    return
                image = self.cache.get(index)
                if image is None:
                    if session is None:
                        session = FitsImageSession(request.source, allow_raw=True, series_idx=request.series)
                    frame, z = (index, request.z) if request.axis == "T" else (request.frame, index)
                    image = self.cache.put(index, session.display_frame(frame, request.channel_index, z))
                if pixels is None:
                    pixels = request.area.pixels((image.shape[0], image.shape[1]))
                original.append(request.area.mean(image, pixels=pixels))
            original_values = np.asarray(original)
            if request.background is None:
                self.ready.emit(request, (coordinates, original_values, np.asarray(processed)))
                return
            if session is not None:
                session.close()
                session = None
            last_update = monotonic()
            self.ready.emit(request, (coordinates, original_values, np.asarray(processed)))
            for index in range(count):
                if self.isInterruptionRequested():
                    return
                result = self.cache.get(index, processed=True)
                if result is None:
                    if session is None:
                        session = BackgroundTuningSession(request.source)
                    assert isinstance(session, BackgroundTuningSession)
                    image = self.cache.get(index)
                    assert image is not None
                    frame, z = (index, request.z) if request.axis == "T" else (request.frame, index)
                    result = self.cache.put(index, session.compute_plane(image, request.background, frame,
                                                                        request.channel, z), processed=True)
                processed.append(request.area.mean(result, pixels=pixels))
                if monotonic() - last_update >= 0.15 or index == count - 1:
                    self.ready.emit(request, (coordinates, original_values, np.asarray(processed)))
                    last_update = monotonic()
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if session is not None:
                session.close()
            if self._own_cache:
                self.cache.close()


class IntensityProfileDialog(QDialog):
    """
    Keep a live curve synchronized with the latest selection without queuing old work.
    """

    def __init__(self, parent: QWidget) -> None:
        """
        Build a movable, resizable plot with a dropdown at the x-axis title.
        """
        super().__init__(parent)
        self.setWindowTitle("Intensity profile")
        self.resize(760, 460)
        self.setModal(False)
        layout = QVBoxLayout(self)
        self.plot = ProfilePlot()
        self.plot.setLabel("left", "Mean intensity")
        layout.addWidget(cast(QWidget, self.plot))
        axis_row = QHBoxLayout()
        axis_row.addStretch()
        self.axis = FocusWheelComboBox()
        self.axis.addItem("Time (frame)", "T")
        self.axis.addItem("Z plane", "Z")
        axis_row.addWidget(self.axis)
        axis_row.addStretch()
        layout.addLayout(axis_row)
        self.legend = QWidget()
        self.legend_layout = QHBoxLayout(self.legend)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(22)
        self._legend_names: tuple[tuple[str, str], ...] = ()
        self.legend.hide()
        layout.addWidget(self.legend)
        self.status = QLabel("Draw an area to show its mean intensity profile.")
        layout.addWidget(self.status)
        self._cache = ProfilePlaneCache()
        self._request: ProfileRequest | None = None
        self._thread: ProfileWorker | None = None
        self._revision = 0
        self._running_revision = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(75)
        self._timer.timeout.connect(self._start)
        self.axis.currentIndexChanged.connect(self._axis_changed)

    def update_request(self, request: ProfileRequest | None) -> None:
        """
        Replace stale requests and schedule a limited live refresh while visible.
        """
        self._request = request
        self._revision += 1
        if self._thread is not None:
            self._thread.requestInterruption()
        if request is None:
            self.plot.clear()
            self._set_legend(())
            self.status.setText("Draw an area to show its mean intensity profile.")
            return
        model = cast(QStandardItemModel, self.axis.model())
        self.axis.setItemText(0, "Time (s)" if request.interval is not None and request.interval > 0 else "Time (frame)")
        for index, enabled in enumerate((request.frames > 1, request.planes > 1)):
            model.item(index).setEnabled(enabled)
        if (self.axis.currentData() == "T" and request.frames < 2
                or self.axis.currentData() == "Z" and request.planes < 2):
            self.axis.setCurrentIndex(0 if request.frames > 1 else 1)
        if self.isVisible() and not self._timer.isActive():
            self.status.setText("Updating profile…")
            self._timer.start()

    def refresh_now(self) -> None:
        """
        Start an explicitly opened profile immediately rather than waiting for drag throttling.
        """
        self.update_request(self._request)
        self._timer.stop()
        self._start()

    def showEvent(self, event: QShowEvent) -> None:
        """
        Fit both axes whenever the profile window is opened or reopened.
        """
        super().showEvent(event)
        if not event.spontaneous():
            self.plot.fit_all()

    def _axis_changed(self) -> None:
        """
        Recalculate using the selected varying dimension.
        """
        self.plot.reset_axis("x")
        self.update_request(self._request)

    def _start(self) -> None:
        """
        Start only the latest request, never overlapping readers or processing jobs.
        """
        if self._thread is not None or self._request is None or not self.isVisible():
            return
        request = replace(self._request, axis=self.axis.currentData())
        if (request.frames if request.axis == "T" else request.planes) < 2:
            return
        self._running_revision = self._revision
        self._thread = ProfileWorker(request, self, self._cache)
        self._thread.ready.connect(self._ready)
        self._thread.failed.connect(self._failed)
        self._thread.finished.connect(self._finished)
        self._thread.start()

    def _ready(self, request: ProfileRequest, result: tuple) -> None:
        """
        Publish curves only when they belong to the current selection.
        """
        if self._running_revision != self._revision:
            return
        x, original, processed = result
        self.plot.clear()
        if request.background is not None:
            self._set_legend((("Original", "#55b7ff"), ("BGSub", "#ffbd55")))
            self.plot.plot(x, original, pen=pg.mkPen("#55b7ff", width=2), name="Original")
            self.plot.plot(x[:processed.size], processed, pen=pg.mkPen("#ffbd55", width=2), name="BGSub")
        else:
            self._set_legend(((request.channel, "#55b7ff"),))
            self.plot.plot(x, original, pen=pg.mkPen("#55b7ff", width=2), name=request.channel)
        progress = (f" · preparing BGSub {processed.size}/{original.size}"
                    if request.background is not None and processed.size < original.size else "")
        self.status.setText(f"{request.channel} · fixed {'Z plane ' + str(request.z + 1) if request.axis == 'T' else 'frame ' + str(request.frame + 1)}{progress}")

    def _set_legend(self, names: tuple[tuple[str, str], ...]) -> None:
        """
        Centre a single row of curve labels beneath the Time/Z selector.
        """
        if names == self._legend_names:
            return
        self._legend_names = names
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            assert item is not None
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.legend_layout.addStretch(1)
        for name, color in names:
            entry = QWidget()
            row = QHBoxLayout(entry)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            swatch = QLabel("━━")
            swatch.setStyleSheet(f"color: {color}; font-weight: bold;")
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setFixedWidth(min(260, label.fontMetrics().horizontalAdvance(name) + 2))
            label.setText(label.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, label.width()))
            label.setToolTip(name)
            row.addWidget(swatch)
            row.addWidget(label)
            self.legend_layout.addWidget(entry)
        self.legend_layout.addStretch(1)
        self.legend.setVisible(bool(names))

    def _failed(self, message: str) -> None:
        """
        Explain current computation failures without publishing stale errors.
        """
        if self._running_revision == self._revision:
            self.status.setText(f"Cannot calculate profile: {message}")

    def _finished(self) -> None:
        """
        Dispose completed workers and service a newer request if one exists.
        """
        thread = self._thread
        if thread is not None:
            thread.wait()
            thread.deleteLater()
        self._thread = None
        if self._running_revision != self._revision and self.isVisible():
            self._timer.start()

    def stop(self, *, clear: bool = False) -> None:
        """
        Stop readers before their window or underlying source is replaced.
        """
        self._timer.stop()
        if self._thread is not None:
            self._thread.requestInterruption()
            self._thread.wait()
        if clear:
            self._request = None
            self._cache.close()
        self._revision += 1

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Stop automatic profile updates when the plot closes.
        """
        self.stop()
        super().closeEvent(event)
