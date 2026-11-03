"""Exercise the completion dialog and its shared GUI/CLI navigation boundary."""

from pathlib import Path
from types import SimpleNamespace
from collections.abc import Callable

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton, QWidget

from fits.gui.theme import get_application
from fits.gui.run_result.dialog import RunResultDialog, show_run_result
from fits.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage
from fits.workflows.runtime.progress.outcome import RunOutcome, RunResult, summarize_run
from fits.workflows.runtime.errors import PipelineCancelled
from fits.workflows.file_management.rebuild import ProcessingPlan
from fits.cli.interactive import run_pipeline_cli
from test_compaction import prepared


@pytest.mark.parametrize('successful', [True, False])
def test_completion_actions_follow_run_outcome(tmp_path: Path, successful: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Always offer the full report, but restrict management hints to successful results.
    """
    app = get_application()
    prepared(tmp_path)
    result = RunResult(RunOutcome.SUCCESS if successful else RunOutcome.FAILED, 'Run outcome', 'Current full report')
    captured: list[str] = []

    def report(path: Path | None, text: str, parent: QWidget) -> SimpleNamespace:
        """
        Observe report content without opening a second modal in this test.
        """
        captured.append(text)
        return SimpleNamespace(exec=lambda: None)

    monkeypatch.setattr('fits.gui.run_result.dialog.ReportDialog', report)
    dialog = RunResultDialog(result, tmp_path)
    try:
        dialog.show()
        app.processEvents()
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        assert ('Manage files…' in buttons) == successful
        assert all(button.toolTip() for title, button in buttons.items() if title != 'Close')
        buttons['Full report…'].click()
        assert captured == ['Current full report']
        if successful:
            buttons['Manage files…'].click()
            assert dialog.manage_requested
    finally:
        dialog.close()


def test_completion_closes_before_management(tmp_path: Path) -> None:
    """
    Let the owner resume its existing navigation after the completion modal closes.
    """
    app = get_application()
    prepared(tmp_path)
    visited: list[bool] = []

    def choose_management() -> None:
        """
        Select management from the actual shared completion dialog.
        """
        dialog = app.activeModalWidget()
        assert isinstance(dialog, RunResultDialog)
        next(button for button in dialog.findChildren(QPushButton) if button.text() == 'Manage files…').click()

    QTimer.singleShot(0, choose_management)
    result = summarize_run(RunProgress(), tmp_path)
    show_run_result(result, tmp_path, manage_files=lambda: visited.append(app.activeModalWidget() is None))
    assert visited == [True]


@pytest.mark.parametrize('cancelled', [False, True])
def test_cli_uses_shared_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancelled: bool) -> None:
    """
    Route interactive CLI completion and intentional cancellation through the same UI.
    """
    get_application()
    settings = tmp_path / 'settings.toml'
    settings.touch()
    captured: list[RunResult] = []
    monkeypatch.setattr('fits.cli.interactive.load_settings', lambda path: {'run_dir': str(tmp_path)})

    def run(**options: object) -> None:
        """
        Simulate completed work without any numerical backend.
        """
        progress = options['run_progress']
        assert isinstance(progress, RunProgress)
        progress.add('experiment', [WorkflowStage.DRAWING])
        progress.update('experiment', WorkflowStage.DRAWING, StageStatus.SKIPPED)
        if cancelled:
            raise PipelineCancelled('User cancelled')

    def completion(result: RunResult, root: Path, *, manage_files: Callable[[], object]) -> None:
        """
        Observe the outcome on the owning Qt thread.
        """
        captured.append(result)

    monkeypatch.setattr('fits.cli.interactive.start_pipeline', run)
    monkeypatch.setattr('fits.cli.interactive.show_run_result', completion)
    run_pipeline_cli(settings)
    assert len(captured) == 1
    assert captured[0].outcome == (RunOutcome.CANCELLED if cancelled else RunOutcome.SUCCESS)


def test_nested_cli_maintenance_suppresses_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Reuse a local event loop for nested maintenance without duplicate completion popups.
    """
    get_application()
    settings = tmp_path / 'settings.toml'
    settings.touch()
    monkeypatch.setattr('fits.cli.interactive.load_settings', lambda path: {'run_dir': str(tmp_path)})
    monkeypatch.setattr('fits.cli.interactive.start_pipeline', lambda **options: None)
    completed: list[RunResult] = []

    def completion(result: RunResult, root: Path, *, manage_files: Callable[[], object]) -> None:
        """
        Start a nested maintenance event loop from the outer completion dialog.
        """
        completed.append(result)
        run_pipeline_cli(settings, maintenance=ProcessingPlan(tmp_path, 'rebuild', {}, ()))

    monkeypatch.setattr('fits.cli.interactive.show_run_result', completion)
    run_pipeline_cli(settings)
    assert len(completed) == 1


def test_management_preserves_main_page_and_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Opening and closing management returns to the same processing subtab and folder.
    """
    from fits.environment import constant as cst
    from fits.gui.main_window.window import FitsMainWindow
    from fits.gui.settings import SettingsAdapter
    app = get_application()
    state, _, _ = prepared(tmp_path)
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', ['Red'])
    window = FitsMainWindow(adapter)
    monkeypatch.setattr('fits.gui.main_window.window.manage_files', lambda *args, **kwargs: False)
    try:
        window.show()
        app.processEvents()
        window._show_step(cst.StepName.BG_SUB)
        assert window.run_browser.select_path(state.workdir)
        window._manage_files()
        assert window._current_step == cst.StepName.BG_SUB
        assert window.run_browser.selected_path == state.workdir
        assert not hasattr(window, 'compact_button')
        assert window.file_size_label.text().startswith('Run size:')
    finally:
        window.close()
