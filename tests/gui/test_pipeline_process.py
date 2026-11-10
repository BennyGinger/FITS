"""Real spawned-worker tests for cancellation, restart and GUI interaction transport."""

from collections.abc import Callable, Iterator
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep
from typing import Any

import numpy as np
import psutil
import pytest
import tifffile
from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fisch.environment.constant import StepName
from fisch.gui.main_window.pipeline_worker import PipelineWorker
from fisch.gui.main_window.window import FischMainWindow
from fisch.gui.settings import SettingsAdapter
from fisch.gui.theme import get_application
from fisch.pipeline import start_pipeline
from fisch.settings.loader import load_settings
from fisch.workflows.checks.models import PreflightReport
from fisch.workflows.experiments import discover_saved_states
from fisch.workflows.runtime.interactive import PipelineInteraction
from fisch.workflows.runtime.interactive.messages import MaskCollectionOutcome, MaskCollectionRequest, TrackEditOutcome, TrackEditRequest
from fisch.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage


pytestmark = pytest.mark.process_pipeline


def _blocking_pipeline(settings_path: Path, run_progress: RunProgress, **options: Any) -> None:
    """
    Simulate uninterruptible native work with an additional descendant process.
    """
    root = Path(load_settings(settings_path)['run_dir'])
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                              start_new_session=os.name == 'posix')
    run_progress.add('busy', (WorkflowStage.PROCESS,))
    run_progress.update('busy', WorkflowStage.PROCESS, StageStatus.ACTIVE)
    (root / 'busy.json').write_text(json.dumps([os.getpid(), child.pid]))
    sleep(120)


def _complete_pipeline(settings_path: Path, run_progress: RunProgress, **options: Any) -> None:
    """
    Complete a second run after cancellation without restarting the GUI.
    """
    run_progress.add('done', (WorkflowStage.PROCESS,))
    run_progress.update('done', WorkflowStage.PROCESS, StageStatus.COMPLETED)
    root = Path(load_settings(settings_path)['run_dir'])
    (root / 'completed.txt').write_text(str(os.getpid()))


def _interactive_pipeline(settings_path: Path,
                          interaction: PipelineInteraction,
                          run_progress: RunProgress,
                          console_handler: logging.Handler,
                          **options: Any,
                          ) -> None:
    """
    Exchange real artifact decisions, mask outcomes, tracking outcomes, logs and progress.
    """
    root = Path(load_settings(settings_path)['run_dir'])
    assert interaction.decide_artifacts(PreflightReport((), (), (), ())) == 'continue'
    request = MaskCollectionRequest('sample', root / 'image.tif', expected_ref_masks=0, requires_reference=False)
    interaction.mask_expected_count(1)
    interaction.mask_request(request)
    outcome = interaction.mask_outcomes.get(timeout=10)
    assert outcome.request == request and outcome.skipped_references == 1
    interaction.mask_input_complete()
    assert interaction.mask_finished.wait(10)
    tracking = TrackEditRequest('sample', root / 'tracking.tif', root / 'image.tif')
    interaction.track_edit_request(tracking)
    assert interaction.track_edit_outcomes.get(timeout=10).request == tracking
    console_handler.handle(logging.LogRecord('process-test', logging.WARNING, __file__, 1,
                                             'Log from isolated pipeline', (), None))
    with run_progress.display.task('Test step', 1):
        run_progress.add('sample', (WorkflowStage.DRAWING,))
        run_progress.update('sample', WorkflowStage.DRAWING, StageStatus.COMPLETED)
        run_progress.display.advance()
    (root / 'interactions.txt').write_text('complete')


def _failing_pipeline(**options: Any) -> None:
    """
    Raise a processing error inside the isolated process.
    """
    raise ValueError('Intentional worker failure')


def _crashing_pipeline(**options: Any) -> None:
    """
    Simulate a native worker crash without running Python exception cleanup.
    """
    os._exit(9)


def _wait_for_finished(window: FischMainWindow, timeout: float = 15) -> None:
    """
    Keep the GUI responsive while waiting for its worker and final status refresh.
    """
    deadline = monotonic() + timeout
    while window._thread is not None and monotonic() < deadline:
        QTest.qWait(10)
    assert window._thread is None, 'Isolated pipeline did not stop.'


@pytest.fixture
def window(tmp_path: Path) -> Iterator[FischMainWindow]:
    """
    Open the main GUI on a real converted movie, with all numerical backends idle.
    """
    app = get_application()
    pixels = np.zeros((3, 16, 16), dtype=np.uint16)
    pixels[:, 4:9, 5:10] = 100
    tifffile.imwrite(tmp_path / 'input.tif', pixels, photometric='minisblack', metadata={'axes': 'TYX'})
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Process test'
    adapter.set_field_value(StepName.CONVERT, 'channel_labels', ['Red'])
    adapter.set_runtime_value('execution', 'batch')
    start_pipeline(adapter.save_to_run_dir(), terminal_progress=False)
    main = FischMainWindow(adapter)
    main.show()
    app.processEvents()
    yield main
    if main._worker is not None:
        main._worker.interaction.cancel()
        _wait_for_finished(main)
    main.close()
    main.deleteLater()
    app.processEvents()


def test_stop_run_kills_busy_worker_and_descendant_then_allows_restart(window: FischMainWindow,
                                                                    tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch,
                                                                    ) -> None:
    """
    Stop active native work promptly, retain the GUI and release the run lock for another run.
    """
    def blocking_worker(*args: Any, **kwargs: Any) -> PipelineWorker:
        """
        Use a spawn-safe blocking backend while retaining the real GUI process supervisor.
        """
        return PipelineWorker(*args, runner=_blocking_pipeline, **kwargs)

    monkeypatch.setattr('fisch.gui.main_window.window.PipelineWorker', blocking_worker)
    monkeypatch.setattr('fisch.gui.main_window.window.confirm_stop', lambda *args, **kwargs: True)
    window._run_pipeline()
    assert window._run_progress is not None
    deadline = monotonic() + 20
    ready = tmp_path / 'busy.json'
    while (not ready.is_file() or not window._run_progress.snapshot()) and monotonic() < deadline:
        QTest.qWait(10)
    assert ready.is_file()
    pids = json.loads(ready.read_text())
    assert pids[0] != os.getpid()
    stopped_at = monotonic()
    window.stop_button.click()
    _wait_for_finished(window, timeout=5)
    assert monotonic() - stopped_at < 3
    assert window._run_cancelled and window.isVisible()
    assert not window.stop_button.isEnabled()
    assert window.quit_button.isEnabled()
    for pid in pids:
        try:
            process = psutil.Process(pid)
            assert not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass

    def complete_worker(*args: Any, **kwargs: Any) -> PipelineWorker:
        """
        Start another isolated worker on the same run after cancellation.
        """
        return PipelineWorker(*args, runner=_complete_pipeline, **kwargs)

    monkeypatch.setattr('fisch.gui.main_window.window.PipelineWorker', complete_worker)
    window._run_pipeline()
    _wait_for_finished(window)
    assert window._last_run_succeeded and window.isVisible()
    assert (tmp_path / 'completed.txt').is_file()


def test_real_pipeline_completes_in_separate_process(window: FischMainWindow, tmp_path: Path) -> None:
    """
    Exercise actual image processing, publication and progress through spawn transport.
    """
    window._editors[StepName.REGISTER_TIME].enable_group.setChecked(True)
    window.adapter.set_field_value(StepName.REGISTER_TIME, 'algorithm', 'scikit')
    window._populate_from_adapter()
    window._run_pipeline()
    _wait_for_finished(window, timeout=25)
    assert window._last_run_succeeded, window._run_error
    state = discover_saved_states(tmp_path)[0]
    output = state.artifact('image_time_registered')
    assert output is not None and output.is_file()
    assert window._run_progress is not None and window._run_progress.snapshot()
    assert window.file_status_label.text() == 'Up to date - editable'


@pytest.mark.parametrize('runner,expected', [(_failing_pipeline, 'Intentional worker failure'),
                                            (_crashing_pipeline, '9')])
def test_process_failure_returns_diagnostics_without_closing_gui(window: FischMainWindow,
                                                               monkeypatch: pytest.MonkeyPatch,
                                                               runner: Callable[..., None],
                                                               expected: str,
                                                               ) -> None:
    """
    Report an isolated processing exception without turning it into a GUI startup error.
    """
    def failing_worker(*args: Any, **kwargs: Any) -> PipelineWorker:
        """
        Inject a spawn-safe failing backend into the actual supervisor.
        """
        return PipelineWorker(*args, runner=runner, **kwargs)

    monkeypatch.setattr('fisch.gui.main_window.window.PipelineWorker', failing_worker)
    window._run_pipeline()
    _wait_for_finished(window)
    assert not window._last_run_succeeded
    assert expected in window._run_error
    assert window.isVisible()


def test_process_transports_interactions_logging_and_progress(tmp_path: Path) -> None:
    """
    Preserve GUI/manual-workflow communication across the process boundary.
    """
    get_application()
    logs: list[str] = []

    class Recorder(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            """
            Capture records delivered by the parent-side worker supervisor.
            """
            logs.append(record.getMessage())

    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    worker = PipelineWorker(adapter.save_to_run_dir(), Recorder(), runner=_interactive_pipeline)
    thread = QThread()
    worker.moveToThread(thread)
    worker.artifact_decision_requested.connect(lambda report: worker.interaction.decisions.put('continue'))
    worker.mask_requested.connect(lambda request: worker.interaction.resolve_mask(
        MaskCollectionOutcome(request, (), (), 1, 0)))
    worker.mask_input_complete.connect(worker.interaction.finish_mask_collection)
    worker.track_edit_requested.connect(lambda request: worker.interaction.resolve_track_edit(TrackEditOutcome(request, None)))
    errors: list[str] = []
    worker.failed.connect(lambda message, details: errors.append(message + details))
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.cancelled.connect(thread.quit)
    thread.started.connect(worker.run)
    thread.start()
    try:
        deadline = monotonic() + 25
        while thread.isRunning() and monotonic() < deadline:
            QTest.qWait(10)
        assert not thread.isRunning(), 'Interactive process did not finish.'
        assert not errors, errors
        assert (tmp_path / 'interactions.txt').read_text() == 'complete'
        assert logs == ['Log from isolated pipeline']
        assert worker.progress.snapshot()[0].stages[WorkflowStage.DRAWING].status == StageStatus.COMPLETED
        display = worker.progress.display.snapshot()
        assert display is not None and display.completed == display.total == 1
    finally:
        if thread.isRunning():
            worker.interaction.cancel()
            deadline = monotonic() + 5
            while thread.isRunning() and monotonic() < deadline:
                QTest.qWait(10)
        thread.wait()
