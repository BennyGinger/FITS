"""Inspect portable state references and master-table identities without processing data."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq
import tomlkit

from fisch.environment import constant as cst
from fisch.environment.paths import experiment_state_path
from fisch.settings.loader import run_settings_path
from fisch.tasks.analysis.aggregate import _condition_values
from fisch.workflows.experiments import ExperimentState, active_states, discover_saved_states
from fisch.workflows.checks.analysis import outdated_master_tables


@dataclass(frozen=True)
class LocationIssue:
    """
    Describe one location-dependent file that needs refreshing.
    """

    path: Path
    reason: str
    folders: tuple[Path, ...]


@dataclass(frozen=True)
class LocationReport:
    """
    Keep location warnings separate from processing-revision conflicts.
    """

    issues: tuple[LocationIssue, ...] = ()

    @property
    def needs_update(self) -> bool:
        """
        Return whether any saved location information differs from the current run.
        """
        return bool(self.issues)

    @property
    def folders(self) -> set[Path]:
        """
        Return the experiment folders highlighted by these warnings.
        """
        return {folder for issue in self.issues for folder in issue.folders or (issue.path.parent,)}

    def describe(self) -> str:
        """
        Explain affected files and the action that resolves their location differences.
        """
        return '\n\n'.join(f'{issue.path}\n  {issue.reason}' for issue in self.issues)


def _state_issue(state: ExperimentState) -> LocationIssue | None:
    """
    Detect absolute or displaced artifact references that can be rebound locally.
    """
    stale = []
    for kind, relative in state.artifacts.items():
        path = state.artifact(kind)
        local = (state.workdir.parent if kind == cst.ARTI_RAW else state.workdir) / relative.name
        if relative.is_absolute() or (path is not None and not path.exists() and local.is_file()):
            stale.append(str(relative))
    if not stale:
        return None
    return LocationIssue(experiment_state_path(state.workdir),
                         'Saved artifact paths need portable references: ' + ', '.join(stale),
                         (state.workdir,))


def _master_issue(root: Path, states: Sequence[ExperimentState], kind: cst.ArtifactType, path: Path) -> LocationIssue | None:
    """
    Compare only master identity/tag columns, streaming batches instead of measurements.
    """
    folders = tuple(state.workdir for state in states)
    try:
        expected: dict[str, tuple[str, ...]] = {}
        depth = 0
        for state in active_states(states):
            source = state.artifact(kind)
            if source is not None and source.is_file():
                conditions = _condition_values(state, root)
                depth = max(depth, len(conditions))
                if pq.ParquetFile(source).metadata.num_rows:
                    expected[state.analysis_experiment_id] = conditions
        master = pq.ParquetFile(path)
        tags = [name for name in master.schema_arrow.names if name.startswith('condition_level_')]
        required = [f'condition_level_{level}' for level in range(1, depth + 1)]
        if 'experiment_id' not in master.schema_arrow.names or set(tags) != set(required):
            return LocationIssue(path, 'Master identity/tag columns differ from the current experiments and condition folders.', folders)
        actual: set[tuple[str | None, ...]] = set()
        for batch in master.iter_batches(columns=['experiment_id', *required]):
            actual.update(zip(*(column.to_pylist() for column in batch.columns)))
        wanted = {(identity, *conditions, *([None] * (depth - len(conditions)))) for identity, conditions in expected.items()}
        if actual == wanted:
            return None
        missing = sorted(set(expected) - {row[0] for row in actual})
        details = 'Master experiment IDs or condition tags differ from the current folder structure.'
        if missing:
            details += '\nCurrent experiments missing from the master: ' + ', '.join(missing[:8])
            if len(missing) > 8:
                details += f' (and {len(missing) - 8} more)'
        changed = {row[0] for row in wanted ^ actual}
        affected = tuple(state.workdir for state in states if state.analysis_experiment_id in changed)
        return LocationIssue(path, details, affected or (root,))
    except (OSError, ValueError) as error:
        return LocationIssue(path, f'Cannot verify master paths/tags: {error}', folders)


def inspect_locations(root: Path, states: Sequence[ExperimentState] | None = None) -> LocationReport:
    """
    Find actual location differences; absent masters and portable per-series tables need no update.
    """
    root = root.resolve()
    states = discover_saved_states(root) if states is None else states
    issues = [issue for state in states if (issue := _state_issue(state)) is not None]
    outdated = set(outdated_master_tables(root, states))
    for kind, name in cst.MASTER_TABLES:
        path = root / name
        if path in outdated:
            # Membership changes require the analysis rebuild path, which also
            # verifies per-series results before refreshing combined tables.
            continue
        if path.is_file() and (issue := _master_issue(root, states, kind, path)) is not None:
            issues.append(issue)
    settings = run_settings_path(root)
    if settings.is_file():
        saved = tomlkit.parse(settings.read_text(encoding='utf-8')).get('run_dir')
        if saved and Path(str(saved)).expanduser().resolve() != root:
            issues.append(LocationIssue(settings, 'Saved run directory differs from the opened run; refresh run-owned settings paths.',
                                        tuple(state.workdir for state in states)))
    return LocationReport(tuple(issues))
