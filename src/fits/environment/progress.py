"""In-memory coordination state for an active pipeline run."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from threading import RLock


class WorkflowStage(StrEnum):
    CONVERT = "convert"
    PREPROCESS = "preprocess"
    PROCESS = "process"
    DRAWING = "drawing"
    ANALYSIS = "analysis"


class StageStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StageProgress:
    status: StageStatus = StageStatus.PENDING
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ExperimentProgress:
    experiment_id: str
    stages: dict[WorkflowStage, StageProgress] = field(default_factory=dict)

    def stage(self, stage: WorkflowStage) -> StageProgress | None:
        """Return a configured stage, or None when that stage is disabled."""
        return self.stages.get(stage)


class RunProgress:
    """Thread-safe progress for every experiment in one pipeline execution."""

    def __init__(self, on_change: Callable[[ExperimentProgress], None] | None = None) -> None:
        self._experiments: dict[str, ExperimentProgress] = {}
        self._lock = RLock()
        self._on_change = on_change

    def add(self, experiment_id: str, required: Iterable[WorkflowStage]) -> ExperimentProgress:
        required = set(required)
        stages = {stage: StageProgress() for stage in required}
        with self._lock:
            progress = ExperimentProgress(experiment_id, stages)
            self._experiments[experiment_id] = progress
        self._notify(progress)
        return progress

    def replace_experiment(self, source_id: str, output_ids: Iterable[str]) -> None:
        """Replace a pre-conversion input with its materialized series branches."""
        output_ids = tuple(dict.fromkeys(output_ids))
        with self._lock:
            source = self._experiments[source_id]
            if output_ids == (source_id,):
                return
            del self._experiments[source_id]
            created = []
            for output_id in output_ids:
                progress = ExperimentProgress(output_id, dict(source.stages))
                self._experiments[output_id] = progress
                created.append(progress)
        for progress in created:
            self._notify(progress)

    def update(self, experiment_id: str, stage: WorkflowStage, status: StageStatus,
               *, error: str | None = None) -> ExperimentProgress:
        with self._lock:
            current = self._experiments[experiment_id]
            stage_progress = StageProgress(status=status, error=error)
            stages = dict(current.stages)
            stages[stage] = stage_progress
            updated = ExperimentProgress(experiment_id, stages)
            self._experiments[experiment_id] = updated
        self._notify(updated)
        return updated

    def experiment(self, experiment_id: str) -> ExperimentProgress:
        with self._lock:
            current = self._experiments[experiment_id]
            return ExperimentProgress(current.experiment_id, dict(current.stages))

    def snapshot(self) -> tuple[ExperimentProgress, ...]:
        with self._lock:
            return tuple(
                ExperimentProgress(progress.experiment_id, dict(progress.stages))
                for progress in self._experiments.values()
            )

    def skip_unfinished(self) -> None:
        """Resolve all pending/active stages when the complete run is stopped."""
        unfinished = {StageStatus.PENDING, StageStatus.ACTIVE}
        with self._lock:
            changed = []
            for experiment_id, current in self._experiments.items():
                stages = {
                    stage: (replace(value, status=StageStatus.SKIPPED)
                            if value.status in unfinished else value)
                    for stage, value in current.stages.items()
                }
                updated = ExperimentProgress(experiment_id, stages)
                self._experiments[experiment_id] = updated
                changed.append(updated)
        for progress in changed:
            self._notify(progress)

    def _notify(self, progress: ExperimentProgress) -> None:
        if self._on_change is not None:
            self._on_change(ExperimentProgress(progress.experiment_id, dict(progress.stages)))
