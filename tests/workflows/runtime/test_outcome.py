"""Run-level success includes intentional drawing skips but excludes unfinished work."""

from pathlib import Path

import pytest
from fisch.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage
from fisch.workflows.runtime.progress.outcome import RunOutcome, summarize_run


@pytest.mark.parametrize('status,error,expected', [
    (StageStatus.COMPLETED, None, RunOutcome.SUCCESS),
    (StageStatus.SKIPPED, None, RunOutcome.SUCCESS),
    (StageStatus.PARTIAL, None, RunOutcome.SUCCESS),
    (StageStatus.FAILED, 'failed task', RunOutcome.FAILED),
    (StageStatus.SKIPPED, 'upstream failure', RunOutcome.FAILED),
    (StageStatus.PENDING, None, RunOutcome.INCOMPLETE),
    (StageStatus.ACTIVE, None, RunOutcome.INCOMPLETE),
])
def test_run_outcomes(status: StageStatus, error: str | None, expected: RunOutcome, tmp_path: Path) -> None:
    """
    Classify the outcome from progress rather than treating every skip as failure.
    """
    progress = RunProgress()
    progress.add('experiment', [WorkflowStage.DRAWING, WorkflowStage.ANALYSIS])
    progress.update('experiment', WorkflowStage.DRAWING, status, error=error)
    progress.update('experiment', WorkflowStage.ANALYSIS, StageStatus.SKIPPED,
                    detail='User skipped reference drawing')
    result = summarize_run(progress, tmp_path)
    assert result.outcome == expected
    assert result.successful == (expected == RunOutcome.SUCCESS)
    assert 'User skipped reference drawing' in result.report


def test_cancelled_and_early_error_reports(tmp_path: Path) -> None:
    """
    Preserve diagnostics even when failure precedes experiment progress.
    """
    progress = RunProgress()
    cancelled = summarize_run(progress, tmp_path, cancelled=True)
    failed = summarize_run(progress, tmp_path, error='Not enough disk space')
    assert cancelled.outcome == RunOutcome.CANCELLED
    assert failed.outcome == RunOutcome.FAILED
    assert 'Not enough disk space' in failed.report
