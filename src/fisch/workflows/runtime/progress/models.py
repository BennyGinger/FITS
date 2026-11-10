"""Immutable models describing workflow progress."""

from dataclasses import dataclass, field
from enum import StrEnum


class WorkflowStage(StrEnum):
    """
    User-facing phases of a workflow run.
    """
    CONVERT = "convert"
    PREPROCESS = "preprocess"
    PROCESS = "process"
    DRAWING = "drawing"
    ANALYSIS = "analysis"


class StageStatus(StrEnum):
    """
    Lifecycle states for one workflow stage.
    """
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StageProgress:
    """
    Current status and optional explanation for one stage.
    """
    status: StageStatus = StageStatus.PENDING
    error: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ExperimentProgress:
    """
    Progress through the configured stages for one experiment.
    """
    experiment_id: str
    stages: dict[WorkflowStage, StageProgress] = field(default_factory=dict)

    def stage(self, stage: WorkflowStage) -> StageProgress | None:
        """
        Return a configured stage, or ``None`` when it is disabled.
        """
        return self.stages.get(stage)
