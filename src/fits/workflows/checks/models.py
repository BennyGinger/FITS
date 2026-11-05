"""Read-only inspection reports shared by checks, runtime and user interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fits.workflows.experiments import ExperimentState
from fits_io.metadata.models import FitsIOMeta


@dataclass(frozen=True)
class RawInputReport:
    """
    Describe raw channel counts, planned acquisition folders and blocking input problems.
    """
    channel_counts: dict[Path, int]
    acquisition_directories: dict[Path, Path]
    problems: tuple[str, ...]

    def describe(self) -> str:
        """
        Format input problems with affected paths and corrective guidance.
        """
        return "\n\n".join(self.problems)


@dataclass(frozen=True)
class RunCompatibility:
    """
    Describe format and layout problems independently of execution completion.
    """
    root: Path
    states: tuple[ExperimentState, ...]
    old_states: tuple[Path, ...]
    files: tuple[Path, ...]
    problems: tuple[str, ...]
    outdated_folders: tuple[Path, ...] = ()

    @property
    def outdated(self) -> bool:
        """
        Return whether active format or layout problems make the run read-only.
        """
        return bool(self.problems)

    def describe(self) -> str:
        """
        Format the compatibility problems for display.
        """
        return '\n'.join(self.problems)


@dataclass(frozen=True)
class ArtifactRecord:
    """
    One artifact's workflow assignment, metadata and detected problem.
    """
    path: Path
    step: str | None
    metadata: FitsIOMeta | None
    problem: str = ""
    legacy: bool = False


@dataclass(frozen=True)
class PreflightReport:
    """
    Temporary artifact inventory and the processing decisions it requires.
    """
    records: tuple[ArtifactRecord, ...]
    overwritten: tuple[str, ...]
    affected: tuple[str, ...]
    states: tuple[ExperimentState, ...]
    rebuild_outputs: tuple[tuple[str, Path], ...] = ()

    @property
    def conflicts(self) -> tuple[ArtifactRecord, ...]:
        """
        Return records with a detected input or compatibility problem.
        """
        return tuple(record for record in self.records if record.problem)

    @property
    def legacy(self) -> bool:
        """
        Return whether any recorded artifact requires migration or rebuilding.
        """
        return any(record.legacy for record in self.records)

    @property
    def needs_decision(self) -> bool:
        """
        Return whether conflicts or overwrites require a caller decision.
        """
        return bool(self.conflicts or self.overwritten)

    def describe(self) -> str:
        """
        Format conflicts, overwrite requests and rebuild outputs for review.
        """
        lines: list[str] = []
        for record in self.records:
            if record.problem:
                lines.append(f"{record.path}\n  {record.problem}")
        if self.overwritten:
            lines.append("\nRequested overwrite: " + ", ".join(self.overwritten))
        if self.affected:
            lines.append("\nAffected downstream steps (including currently disabled steps): " + ", ".join(self.affected))
            for record in self.records:
                if record.step in self.affected:
                    lines.append(f"  {record.path}")
        if self.rebuild_outputs:
            lines.append("\nRebuild plan (when rebuilding is chosen):")
            lines.extend(f"  {step}: {path}" for step, path in self.rebuild_outputs)
        return "\n".join(lines)


class PreflightRequired(ValueError):
    """
    Inspection requires a caller-supplied choice before processing can proceed.
    """
    def __init__(self, report: PreflightReport) -> None:
        """
        Initialize the PreflightRequired state and dependencies.
        """
        self.report = report
        super().__init__("Artifact conflicts require an explicit rebuild/continue decision.\n" + report.describe())
