"""Check the experiment membership recorded in combined analysis tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

import pyarrow.parquet as pq

from fits.environment.constant import ARTI_IMG_RAW, MASTER_TABLES, ArtifactType, StepName
from fits.workflows.experiments import ExperimentState, active_states

if TYPE_CHECKING:
    from fits.workflows.checks.models import ArtifactRecord


MEMBERSHIP_KEY = b'fits_active_experiments'


def master_analysis_steps(paths: Sequence[Path]) -> tuple[StepName, ...]:
    """
    Map combined analysis artifacts to their normal workflow producer steps.
    """
    names = {path.name for path in paths}
    return tuple(step for (_, name), step in zip(MASTER_TABLES, (StepName.EXTRACT, StepName.DISTANCE_PROFILE))
                 if name in names)


def masters_with_outdated_inputs(root: Path, records: Sequence[ArtifactRecord]) -> tuple[Path, ...]:
    """
    Propagate per-series analysis conflicts to their existing combined tables.
    """
    stale = {record.step for record in records if record.problem}
    return tuple(root / name for (_, name), step in zip(MASTER_TABLES, (StepName.EXTRACT, StepName.DISTANCE_PROFILE))
                 if step in stale and (root / name).is_file())


def include_master_analysis(config: Mapping[str, Any],
                             paths: Sequence[Path],
                             records: Sequence[ArtifactRecord],
                             ) -> dict[str, Any]:
    """
    Enable per-series analysis only when a master rebuild needs missing or stale results.
    """
    result = deepcopy(dict(config))
    names = {path.name for path in paths}
    for (_, name), step in zip(MASTER_TABLES, (StepName.EXTRACT, StepName.DISTANCE_PROFILE)):
        if name in names and any(record.problem and record.step == step for record in records):
            result.setdefault(step, {})['enabled'] = True
    return result


def analysis_membership(states: Sequence[ExperimentState], artifact_kind: ArtifactType) -> list[str]:
    """
    Identify active series by portable names and existing artifact revisions.
    """
    from fits.workflows.artifacts.provenance import read_metadata

    members: list[str] = []
    for state in active_states(states):
        revision = None
        for kind in (artifact_kind, ARTI_IMG_RAW):
            source = state.artifact(kind)
            if source is not None and source.is_file():
                revision = read_metadata(source).fits_io.created_at
                if revision:
                    break
        # Revision stamps distinguish identically named acquisitions in different
        # conditions and survive folder relocation. Older unstamped sources use
        # their existing run-relative identity until they are rebuilt.
        members.append(f'{state.portable_experiment_id}:{revision}' if revision else state.analysis_experiment_id)
    return sorted(members)


def outdated_master_tables(root: Path, states: Sequence[ExperimentState]) -> tuple[Path, ...]:
    """
    Detect changed membership, including older masters without a membership record.
    """
    active = active_states(states)
    outdated: list[Path] = []
    for kind, name in MASTER_TABLES:
        path = root / name
        if not path.is_file():
            if any((source := state.artifact(kind)) is not None and source.is_file() for state in active):
                outdated.append(path)
            continue
        try:
            master = pq.ParquetFile(path)
            recorded = (master.schema_arrow.metadata or {}).get(MEMBERSHIP_KEY)
            if recorded is not None:
                matches = json.loads(recorded) == analysis_membership(active, kind)
            else:
                # Older masters have no membership stamp. Preserve all-active
                # legacy behavior; an explicit exclusion requires one rebuild.
                matches = not any(state.excluded for state in states)
            if not matches:
                outdated.append(path)
        except (OSError, ValueError, KeyError):
            outdated.append(path)
    return tuple(outdated)
