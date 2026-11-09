"""Classify completed runs independently of Qt and user-interface navigation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fits.workflows.runtime.progress import RunProgress, StageStatus, format_run_report


class RunOutcome(StrEnum):
    """
    Distinguish successful, unfinished, failed and cancelled pipeline runs.
    """
    SUCCESS = 'success'
    INCOMPLETE = 'incomplete'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass(frozen=True)
class RunResult:
    """
    Carry a shared outcome, concise summary and complete report to either interface.
    """
    outcome: RunOutcome
    message: str
    report: str

    @property
    def successful(self) -> bool:
        """
        Return whether all requested work finished without a processing failure.
        """
        return self.outcome == RunOutcome.SUCCESS


def summarize_run(progress: RunProgress, root: Path, *, error: str = '', cancelled: bool = False) -> RunResult:
    """
    Treat intentional drawing skips as successful while preserving real failures.
    """
    stages = [stage for experiment in progress.snapshot() for stage in experiment.stages.values()]
    if cancelled:
        outcome, message = RunOutcome.CANCELLED, 'Pipeline run stopped. Restarting may require Overwrite for affected steps.'
    elif error or any(stage.status == StageStatus.FAILED or stage.error for stage in stages):
        outcome, message = RunOutcome.FAILED, 'Pipeline run finished with failures. Completed work has been kept.'
    elif any(stage.status in (StageStatus.PENDING, StageStatus.ACTIVE) for stage in stages):
        outcome, message = RunOutcome.INCOMPLETE, 'Pipeline run is incomplete. Review the report for unfinished work.'
    else:
        outcome, message = RunOutcome.SUCCESS, 'Pipeline run finished successfully.'
    skipped = sum(stage.status in (StageStatus.SKIPPED, StageStatus.PARTIAL) for stage in stages)
    if skipped:
        message += f' {skipped} stage(s) were skipped or completed partially; see the full report.'
    report = format_run_report(progress, root, include_header=True)
    if error:
        report += '\n\nRun error\n---------\n' + error
    return RunResult(outcome, message, report)
