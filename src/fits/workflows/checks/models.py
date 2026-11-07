"""Read-only inspection reports shared by checks, runtime and user interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fits.workflows.experiments import ExperimentState
from fits_io.metadata.models import FitsIOMeta


@dataclass(frozen=True)
class RawInputReport:
    """
    Describe raw channel/frame counts, acquisition folders, blocking problems and warnings.
    """
    channel_counts: dict[Path, int]
    acquisition_directories: dict[Path, Path]
    problems: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    frame_counts: dict[Path, tuple[int, ...]] = field(default_factory=dict)
    channel_colors: dict[Path, list[str | None] | None] = field(default_factory=dict)

    @property
    def expected_channel_colors(self) -> list[str | None] | None:
        """
        Return colors that agree across inputs; conflicting or missing colors remain unknown.
        """
        counts = set(self.channel_counts.values())
        if len(counts) != 1 or not self.channel_colors:
            return None
        count = next(iter(counts))
        palettes = [self.channel_colors.get(path) for path in self.channel_counts]
        colors: list[str | None] = []
        for index in range(count):
            values = {palette[index] if palette is not None and len(palette) == count else None
                      for palette in palettes}
            colors.append(next(iter(values)) if len(values) == 1 else None)
        return colors

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
    disabled_steps: tuple[str, ...] = ()
    outdated_masters: tuple[Path, ...] = ()

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
    def blocking_conflicts(self) -> tuple[ArtifactRecord, ...]:
        """
        Preserve stale bypassed results without requiring a processing decision.
        """
        from fits.environment.constant import StepName
        from fits.workflows.artifacts.branch_masks import is_branch

        analyses_bypassed = {StepName.EXTRACT, StepName.DISTANCE_PROFILE} <= set(self.disabled_steps)
        return tuple(record for record in self.conflicts if record.legacy or (
            record.step not in self.disabled_steps and not (analyses_bypassed and is_branch(record.path))))

    @property
    def warnings(self) -> tuple[str, ...]:
        """
        Summarize preserved bypassed results that are stale or affected by an overwrite.
        """
        from fits.workflows.checks.planning import overwrite_dependents

        affected = (*self.conflicts, *overwrite_dependents(self.records, self.overwritten))
        steps = sorted({record.step for record in affected if record.step in self.disabled_steps and record.step is not None})
        return tuple(f"Bypassed step '{step}': existing results are preserved and may be outdated. "
                     "They will be checked before reuse when this step is included again." for step in steps)

    @property
    def needs_decision(self) -> bool:
        """
        Return whether conflicts or overwrites affecting saved downstream files need review.
        """
        from fits.workflows.checks.planning import overwrite_affects_existing

        return bool(self.outdated_masters or self.blocking_conflicts
                    or overwrite_affects_existing(self.records, self.overwritten, self.disabled_steps))

    @property
    def analysis_only_rebuild(self) -> bool:
        """
        Identify master rebuilds that can reuse valid individual measurements.
        """
        return bool(self.outdated_masters and not self.blocking_conflicts)

    def describe(self) -> str:
        """
        Format conflicts, overwrite requests and rebuild outputs for review.
        """
        lines: list[str] = []
        if self.outdated_masters:
            lines.append('Combined analysis no longer matches the active experiments or their results. Rebuild:')
            lines.extend(f'  {path}' for path in self.outdated_masters)
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
