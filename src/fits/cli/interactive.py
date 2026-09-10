"""Run the configured pipeline with an on-demand mask collection window."""
from __future__ import annotations

from pathlib import Path
import sys
from threading import Thread

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from fits.gui.theme import apply_dark_theme
from fits.gui.viewer.collection_window import MaskCollectionWindow
from fits.environment.progress import RunProgress
from fits.pipeline import SETTINGS_PATH, start_pipeline
from fits.settings.loader import load_settings
from fits.workflows.interactive import MaskInteraction, PipelineCancelled


class _PipelineSignals(QObject):
    mask_requested = Signal(object)
    mask_input_complete = Signal()
    mask_expected_count = Signal(int)
    stopped = Signal(object)


def run_pipeline_cli(settings_path: Path | None = None) -> None:
    """Run the CLI pipeline and show mask collection when settings request it."""
    config_path = (settings_path or SETTINGS_PATH).expanduser().resolve()
    config = load_settings(config_path)
    run_dir = Path(config["run_dir"]).expanduser().resolve()

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([sys.argv[0]])
    app.setApplicationName("FITS")
    app.setQuitOnLastWindowClosed(False)
    apply_dark_theme(app)

    signals = _PipelineSignals()
    interaction = MaskInteraction(
        signals.mask_requested.emit,
        signals.mask_input_complete.emit,
        signals.mask_expected_count.emit,
    )
    progress = RunProgress()
    collection: MaskCollectionWindow | None = None
    mask_expected_count: int | None = None
    result: list[BaseException | None] = []

    def request_mask(request) -> None:
        nonlocal collection
        if collection is None:
            collection = MaskCollectionWindow(preview=False, run_dir=run_dir)
            if mask_expected_count is not None:
                collection.set_expected_experiments(mask_expected_count)
            collection.experiment_finalized.connect(interaction.resolve)
            collection.collection_finished.connect(interaction.finish)
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

    def stop(error) -> None:
        result.append(error)
        if collection is not None:
            collection._ended = True
            collection.close()
        app.quit()

    signals.mask_requested.connect(request_mask)
    signals.mask_input_complete.connect(input_complete)
    signals.mask_expected_count.connect(expected_count)
    signals.stopped.connect(stop)

    def work() -> None:
        try:
            start_pipeline(settings_path=config_path, mask_interaction=interaction,
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
