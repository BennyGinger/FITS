"""Persistent step/progress/elapsed strip for the main activity-log header."""

from time import monotonic

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from fits.workflows.runtime.progress import RunProgress, StageStatus


class PipelineProgressWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress: RunProgress | None = None
        self._started = 0.0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 0, 6)
        layout.setSpacing(12)
        self.step_label = QLabel("Idle")
        self.step_label.setFixedWidth(160)
        layout.addWidget(self.step_label)
        self.bar = QProgressBar()
        self.bar.setMinimumWidth(180)
        self.bar.setFixedHeight(24)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setFormat("—")
        self.bar.setStyleSheet(
            "QProgressBar { border: 1px solid #405773; border-radius: 3px; text-align: center; }"
            "QProgressBar::chunk { background: #399df2; }")
        layout.addWidget(self.bar, 1)
        self.elapsed_label = QLabel("Elapsed 00:00:00")
        # Reserve long durations too, so changing digits never moves the bar.
        self.elapsed_label.setFixedWidth(
            self.elapsed_label.fontMetrics().horizontalAdvance("Elapsed 8888:88:88") + 8)
        layout.addWidget(self.elapsed_label)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)

    def begin(self, progress: RunProgress | None) -> None:
        self._progress = progress
        self._started = monotonic()
        self._timer.start()
        self.refresh()

    def finish(self) -> None:
        if self._timer.isActive():
            self.refresh()
            self._timer.stop()
            if self.bar.maximum() == 0:
                self.bar.setRange(0, 1)
                self.bar.setValue(0)
                self.bar.setFormat("—")
                self.step_label.setText("Idle")

    def refresh(self) -> None:
        snapshot = self._progress.display.snapshot() if self._progress is not None else None
        if snapshot is not None:
            name = snapshot.name
            completed, total, elapsed = snapshot.completed, snapshot.total, snapshot.elapsed
        else:
            # Interactive execution has no Rich bar. Its configured stages
            # supply the overall count, including failed/skipped terminal work.
            stages = [stage for experiment in self._progress.snapshot()
                      for stage in experiment.stages.values()] if self._progress is not None else []
            terminal = {StageStatus.COMPLETED, StageStatus.PARTIAL,
                        StageStatus.SKIPPED, StageStatus.FAILED}
            completed = sum(stage.status in terminal for stage in stages)
            total = len(stages)
            elapsed = monotonic() - self._started
            name = "Pipeline" if stages else "Preparing…"
        self.step_label.setText(name)
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(completed)
            self.bar.setFormat("%v / %m")
        elif self._timer.isActive():
            self.bar.setRange(0, 0)
        seconds = int(elapsed)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.elapsed_label.setText(f"Elapsed {hours:02d}:{minutes:02d}:{seconds:02d}")
