"""Run the configured pipeline with its on-demand interactive windows."""
from __future__ import annotations

from pathlib import Path
import sys
from threading import Thread
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from fits.gui.theme import apply_dark_theme
from fits.gui.viewer.masks import MaskCollectionWindow
from fits.workflows.runtime.progress import RunProgress
from fits.pipeline import start_pipeline
from fits.settings.loader import load_settings
from fits.workflows.runtime.interactive import PipelineCancelled, PipelineInteraction


class _PipelineSignals(QObject):
    mask_requested = Signal(object)
    track_edit_requested = Signal(object)
    mask_input_complete = Signal()
    mask_expected_count = Signal(int)
    stopped = Signal(object)


def run_pipeline_cli(settings_path: Path) -> None:
    """

    Show the mask collector when the configured pipeline requests input.

    """
    config_path = settings_path.expanduser().resolve()
    config = load_settings(config_path)
    run_dir = Path(config["run_dir"]).expanduser().resolve()

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([sys.argv[0]])
    app.setApplicationName("FITS")
    app.setQuitOnLastWindowClosed(False)
    apply_dark_theme(app)

    signals = _PipelineSignals()
    interaction = PipelineInteraction(
        signals.mask_requested.emit,
        signals.mask_input_complete.emit,
        signals.mask_expected_count.emit,
        signals.track_edit_requested.emit,
    )
    progress = RunProgress()
    collection: MaskCollectionWindow | None = None
    tracking_editor = None
    tracking_requests = deque()
    mask_expected_count: int | None = None
    result: list[BaseException | None] = []

    def request_mask(request) -> None:
        nonlocal collection
        if collection is None:
            collection = MaskCollectionWindow(preview=False, run_dir=run_dir)
            if mask_expected_count is not None:
                collection.set_expected_experiments(mask_expected_count)
            collection.experiment_finalized.connect(interaction.resolve_mask)
            collection.collection_finished.connect(interaction.finish_mask_collection)
            collection.cancellation_requested.connect(interaction.cancel)
            collection.show()
        collection.enqueue_experiment(request)

    def input_complete() -> None:
        if collection is not None and not collection._ended:
            collection.no_more_requests()

    def expected_count(count: int) -> None:
        nonlocal mask_expected_count
        mask_expected_count = count
        if collection is not None:
            collection.set_expected_experiments(count)

    def open_next_tracking_edit() -> None:
        nonlocal tracking_editor
        if tracking_editor is not None or not tracking_requests:
            return
        from fits.gui.viewer.tracking import TrackingViewerWindow

        request = tracking_requests.popleft()
        tracking_editor = TrackingViewerWindow(
            experiments_dir=run_dir,
            tracking_path=request.tracking_path,
            editing_enabled=True,
            pipeline_request=request,
        )

        def finalized(outcome) -> None:
            nonlocal tracking_editor
            interaction.resolve_track_edit(outcome)
            tracking_editor = None
            QTimer.singleShot(0, open_next_tracking_edit)

        tracking_editor.tracking_finalized.connect(finalized)
        tracking_editor.show()

    def request_tracking_edit(request) -> None:
        tracking_requests.append(request)
        open_next_tracking_edit()

    def stop(error) -> None:
        nonlocal tracking_editor
        result.append(error)
        if collection is not None:
            collection._ended = True
            collection.close()
        tracking_requests.clear()
        if tracking_editor is not None:
            tracking_editor._pipeline_resolved = True
            tracking_editor.close()
            tracking_editor = None
        app.quit()

    signals.mask_requested.connect(request_mask)
    signals.mask_input_complete.connect(input_complete)
    signals.mask_expected_count.connect(expected_count)
    signals.track_edit_requested.connect(request_tracking_edit)
    signals.stopped.connect(stop)

    def work() -> None:
        try:
            start_pipeline(settings_path=config_path, interaction=interaction,
                           run_progress=progress)
        except PipelineCancelled:
            signals.stopped.emit(None)
        except BaseException as error:
            signals.stopped.emit(error)
        else:
            signals.stopped.emit(None)

    worker = Thread(target=work, name="fits-cli-pipeline")
    QTimer.singleShot(0, worker.start)
    app.exec()
    worker.join()
    if result and result[0] is not None:
        raise result[0]
