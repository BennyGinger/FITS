"""Human-readable reports derived from one in-memory pipeline run."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fits.environment.progress import RunProgress, StageStatus, WorkflowStage


STAGE_TITLES = {
    WorkflowStage.CONVERT: "Conversion",
    WorkflowStage.PREPROCESS: "Preprocessing",
    WorkflowStage.PROCESS: "Processing",
    WorkflowStage.DRAWING: "Drawing",
    WorkflowStage.ANALYSIS: "Analysis",
}


def format_run_report(progress: RunProgress, run_dir: Path | None = None, *,
                      include_header: bool = False) -> str:
    snapshot = progress.snapshot()
    lines: list[str] = []
    if include_header:
        lines.extend(("FITS pipeline report", f"Created: {datetime.now():%Y-%m-%d %H:%M:%S}", ""))

    experiment_counts = {status: 0 for status in StageStatus}
    for experiment in snapshot:
        statuses = [stage.status for stage in experiment.stages.values()]
        if StageStatus.FAILED in statuses:
            outcome = StageStatus.FAILED
        elif StageStatus.PARTIAL in statuses:
            outcome = StageStatus.PARTIAL
        elif statuses and all(status == StageStatus.SKIPPED for status in statuses):
            outcome = StageStatus.SKIPPED
        elif any(status in (StageStatus.PENDING, StageStatus.ACTIVE) for status in statuses):
            outcome = StageStatus.ACTIVE
        else:
            outcome = StageStatus.COMPLETED
        experiment_counts[outcome] += 1
    lines.append(
        "Experiments: "
        f"{experiment_counts[StageStatus.COMPLETED]} completed / "
        f"{experiment_counts[StageStatus.PARTIAL]} partial / "
        f"{experiment_counts[StageStatus.SKIPPED]} skipped / "
        f"{experiment_counts[StageStatus.FAILED]} failed")
    lines.append("")

    details: list[str] = []
    for stage in WorkflowStage:
        records = [(experiment, experiment.stage(stage)) for experiment in snapshot]
        records = [(experiment, record) for experiment, record in records if record is not None]
        if not records:
            continue
        counts = {status: sum(record.status == status for _, record in records)
                  for status in StageStatus}
        lines.append(
            f"{STAGE_TITLES[stage]}: {counts[StageStatus.COMPLETED]} completed / "
            f"{counts[StageStatus.PARTIAL]} partial / "
            f"{counts[StageStatus.SKIPPED]} skipped / "
            f"{counts[StageStatus.FAILED]} failed")
        for experiment, record in records:
            if record.status not in (StageStatus.PARTIAL, StageStatus.SKIPPED, StageStatus.FAILED):
                continue
            name = _short_path(experiment.experiment_id, run_dir)
            explanation = record.error or record.detail
            if explanation:
                explanation = _short_text(explanation, run_dir)
                details.append(
                    f"{name}\n  {STAGE_TITLES[stage]}: {record.status.value} — {explanation}")
            elif record.status == StageStatus.FAILED:
                details.append(f"{name}\n  {STAGE_TITLES[stage]}: failed — Unknown error")
    if details:
        lines.extend(("", "Experiment details", "------------------", *details))
    return "\n".join(lines)


def _short_path(value: str, run_dir: Path | None) -> str:
    if run_dir is not None:
        try:
            return Path(value).relative_to(run_dir).as_posix()
        except ValueError:
            pass
    return value


def _short_text(value: str, run_dir: Path | None) -> str:
    return value.replace(run_dir.as_posix(), ".") if run_dir is not None else value
