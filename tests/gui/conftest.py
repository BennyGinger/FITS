"""Keep unrelated GUI tests from waiting on the new completion modal."""

from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget
from fits.workflows.runtime.progress.outcome import RunResult


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
