"""Shared GUI test cleanup, completion routing and local fake-backend execution."""

from collections.abc import Callable, Iterator
from pathlib import Path
import gc

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from fisch.gui.segmentation_models.loader import ModelOptionsLoader
from fisch.workflows.runtime.progress.outcome import RunResult
from fisch.gui.main_window.pipeline_worker import PipelineWorker


def pytest_configure(config: pytest.Config) -> None:
    """
    Register the isolated-process integration checks without changing installation inputs.
    """
    config.addinivalue_line('markers', 'process_pipeline: exercise the real isolated GUI pipeline process')


@pytest.fixture(autouse=True)
def inline_fake_backends(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep patched GUI test backends local; dedicated process tests exercise real isolation.
    """
    if request.node.get_closest_marker('process_pipeline') is None:
        monkeypatch.setattr(PipelineWorker, 'run', PipelineWorker.run_inline)


@pytest.fixture(scope='session', autouse=True)
def finish_background_model_discovery() -> Iterator[None]:
    """
    Wait for GUI workers when tests finish without entering QApplication.exec().
    """
    app = QApplication.instance() or QApplication([])
    automatic_gc = gc.isenabled()
    gc.disable()
    yield
    if app is not None:
        loader = app.findChild(ModelOptionsLoader, 'fisch-cellpose-model-options')
        if loader is not None:
            loader.wait()
    if automatic_gc:
        gc.enable()


@pytest.fixture(autouse=True)
def collect_qt_objects_on_main_thread() -> Iterator[None]:
    """
    Collect closed widget cycles before a native worker can collect them instead.
    """
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def dismiss_run_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Let integration tests override completion routing without blocking existing tests.
    """
    def dismiss(result: RunResult,
                root: Path,
                parent: QWidget | None = None,
                *,
                manage_files: Callable[[], object],
                ) -> None:
        """
        Leave outcome and navigation assertions to focused completion-dialog tests.
        """
        return None

    monkeypatch.setattr('fisch.gui.main_window.window.show_run_result', dismiss)
    monkeypatch.setattr('fisch.cli.interactive.show_run_result', dismiss)
