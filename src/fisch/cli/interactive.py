"""Run the configured pipeline with its on-demand interactive windows."""
from __future__ import annotations

from typing import Any
from collections.abc import Callable
from fisch.workflows.checks.models import PreflightReport
from fisch.workflows.file_management.rebuild import ProcessingPlan
from fisch.workflows.runtime.interactive.messages import MaskCollectionRequest, TrackEditRequest, TrackEditOutcome
from pathlib import Path
import sys
from threading import Thread
from collections import deque
from PySide6.QtCore import QObject, QEventLoop, QTimer, Signal
from PySide6.QtWidgets import QApplication
from fisch.gui.theme import apply_dark_theme
from fisch.gui.viewer.masks import MaskCollectionWindow
from fisch.workflows.runtime.progress import RunProgress, StageStatus
from fisch.pipeline import start_pipeline
from fisch.channel_labels.lock import run_write_guard
from fisch.settings.loader import load_settings
from fisch.workflows.runtime.interactive import PipelineCancelled, PipelineInteraction
from fisch.gui.artifact_decisions import choose_artifacts
from fisch.gui.run_result.dialog import show_run_result
from fisch.gui.file_management.manager import manage_files
from fisch.workflows.runtime.progress.outcome import summarize_run
import traceback


class _PipelineSignals(QObject):
    mask_requested = Signal(object)
    track_edit_requested = Signal(object)
    mask_input_complete = Signal()
    mask_expected_count = Signal(int)
    stopped = Signal(object)
    artifact_decision_requested = Signal(object)


def run_pipeline_cli(settings_path: Path,
                     *,
                     artifact_decision: Callable[[PreflightReport], str] | None = None,
                     upgrading: bool = False,
                     maintenance: ProcessingPlan | None = None,
                     show_completion: bool = True,
                     ) -> None:
    """
    Show the mask collector when the configured pipeline requests input.
    """
    config_path = settings_path.expanduser().resolve()
    config = load_settings(config_path)
    run_dir = Path(config["run_dir"]).expanduser().resolve()

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([sys.argv[0]])
    app.setApplicationName("FIScH")
    quit_on_close = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    apply_dark_theme(app)

    loop = QEventLoop()
    signals = _PipelineSignals()
    interaction = PipelineInteraction(signals.mask_requested.emit,
                                      signals.mask_input_complete.emit,
                                      signals.mask_expected_count.emit,
                                      signals.track_edit_requested.emit,
                                      decision_request=signals.artifact_decision_requested.emit,
                                      )
    progress = RunProgress()
    collection: MaskCollectionWindow | None = None
    tracking_editor = None
    tracking_requests = deque()
    mask_expected_count: int | None = None
    result: list[BaseException | None] = []

    def request_mask(request: MaskCollectionRequest) -> None:
        """
        Request mask.
        """
        nonlocal collection
        if collection is None:
            collection = MaskCollectionWindow(preview=False, run_dir=run_dir)
            if mask_expected_count is not None:
                collection.set_expected_experiments(mask_expected_count)
            collection.experiment_finalized.connect(interaction.resolve_mask)
            collection.collection_finished.connect(interaction.finish_mask_collection)
            collection.show()
        collection.enqueue_experiment(request)

    def input_complete() -> None:
        """
        Input complete.
        """
        if collection is not None and not collection._ended:
            collection.no_more_requests()

    def expected_count(count: int) -> None:
        """
        Expected count.
        """
        nonlocal mask_expected_count
        mask_expected_count = count
        if collection is not None:
            collection.set_expected_experiments(count)

    def open_next_tracking_edit() -> None:
        """
        Open next tracking edit.
        """
        nonlocal tracking_editor
        if tracking_editor is not None or not tracking_requests:
            return
        from fisch.gui.viewer.tracking import TrackingViewerWindow

        request = tracking_requests.popleft()
        tracking_editor = TrackingViewerWindow(experiments_dir=run_dir,
                                               tracking_path=request.tracking_path,
                                               editing_enabled=True,
                                               pipeline_request=request,
                                               )

        def finalized(outcome: TrackEditOutcome) -> None:
            """
            Return the current finalized.
            """
            nonlocal tracking_editor
            interaction.resolve_track_edit(outcome)
            tracking_editor = None
            QTimer.singleShot(0, open_next_tracking_edit)

        tracking_editor.tracking_finalized.connect(finalized)
        tracking_editor.show()

    def request_tracking_edit(request: TrackEditRequest) -> None:
        """
        Request tracking edit.
        """
        tracking_requests.append(request)
        open_next_tracking_edit()

    def stop(error: BaseException | None) -> None:
        """
        Return the current stop.
        """
        nonlocal tracking_editor
        result.append(None if isinstance(error, PipelineCancelled) and not upgrading and maintenance is None else error)
        if collection is not None:
            collection._ended = True
            collection.close()
        tracking_requests.clear()
        if tracking_editor is not None:
            tracking_editor._pipeline_resolved = True
            tracking_editor.close()
            tracking_editor = None
        if show_completion and maintenance is None and not upgrading and artifact_decision is None:
            summary = summarize_run(progress, run_dir,
                                    error=''.join(traceback.format_exception(error)) if error is not None and not isinstance(error, PipelineCancelled) else '',
                                    cancelled=isinstance(error, PipelineCancelled))
            show_run_result(summary, run_dir, manage_files=lambda: manage_files(run_dir))
        loop.quit()

    signals.mask_requested.connect(request_mask)
    signals.mask_input_complete.connect(input_complete)
    signals.mask_expected_count.connect(expected_count)
    signals.track_edit_requested.connect(request_tracking_edit)
    signals.stopped.connect(stop)
    signals.artifact_decision_requested.connect(lambda report: interaction.decisions.put(choose_artifacts(report)),
                                                )

    def work() -> None:
        """
        Run pipeline processing in the background thread.
        """
        try:
            with run_write_guard(run_dir):
                options: dict[str, Any] = {"artifact_decision": artifact_decision} if artifact_decision else {}
                start_pipeline(settings_path=config_path,
                               interaction=interaction,
                               run_progress=progress,
                               upgrading=upgrading,
                               **({'maintenance': maintenance} if maintenance is not None else {}),
                               **options,
                               )
        except PipelineCancelled as error:
            signals.stopped.emit(error)
        except BaseException as error:
            signals.stopped.emit(error)
        else:
            signals.stopped.emit(None)

    worker = Thread(target=work, name="fisch-cli-pipeline")
    QTimer.singleShot(0, worker.start)
    try:
        loop.exec()
    finally:
        worker.join()
        app.setQuitOnLastWindowClosed(quit_on_close)
    if result and result[0] is not None:
        raise result[0]
    if (upgrading or maintenance is not None) and any(stage.status == StageStatus.FAILED or stage.error is not None
                         for experiment in progress.snapshot() for stage in experiment.stages.values()):
        raise ValueError('Some experiments failed during upgrading. Completed work and retained history are preserved; resume through Manage files.')
