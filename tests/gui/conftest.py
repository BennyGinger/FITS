"""Keep unrelated GUI tests from waiting on the new completion modal."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from fits.gui.segmentation_models.loader import ModelOptionsLoader
from fits.workflows.runtime.progress.outcome import RunResult


@pytest.fixture(scope='session', autouse=True)
def finish_background_model_discovery() -> Iterator[None]:
    """
    Wait for GUI workers when tests finish without entering QApplication.exec().
    """
    yield
    app = QApplication.instance()
    if app is not None:
        loader = app.findChild(ModelOptionsLoader, 'fits-cellpose-model-options')
        if loader is not None:
            loader.wait()


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

    monkeypatch.setattr('fits.gui.main_window.window.show_run_result', dismiss)
    monkeypatch.setattr('fits.cli.interactive.show_run_result', dismiss)
