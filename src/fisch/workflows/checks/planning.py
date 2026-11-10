"""Shared workflow ordering and rebuild-source selection for preflight checks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from pathlib import Path

from fisch.environment import constant as cst
from fisch.workflows.artifacts.branch_masks import is_branch
from fisch.workflows.checks.models import ArtifactRecord
from fisch.workflows.experiments import ExperimentState


def overwrite_steps(config: Mapping[str, Any]) -> tuple[cst.StepName, ...]:
    """
    Return enabled overwrite requests in workflow order.
    """
    return tuple(step for step in cst.WORKFLOW_ORDER
                 if config.get(step, {}).get("enabled") and config[step].get("params", {}).get("overwrite"))


def overwrite_dependents(records: Sequence[ArtifactRecord], overwritten: Iterable[str]) -> tuple[ArtifactRecord, ...]:
    """
    Find existing downstream files affected by overwrites in the same experiment.
    """
    selected_steps = set(overwritten)
    geometry_steps = {cst.StepName.CONVERT, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME}
    affected: dict[Path, ArtifactRecord] = {}
    for selected in records:
        if selected.step is None or selected.step not in selected_steps or not selected.path.is_file():
            continue
        downstream = set(downstream_steps((selected.step,)))
        for record in records:
            if record.path == selected.path or record.path.parent != selected.path.parent or not record.path.is_file():
                continue
            if record.step in downstream or (selected.step in geometry_steps and is_branch(record.path)):
                affected[record.path] = record
    return tuple(affected.values())


def overwrite_affects_existing(records: Sequence[ArtifactRecord],
                               overwritten: Iterable[str],
                               disabled_steps: Iterable[str] = (),
                               ) -> bool:
    """
    Review overwrites only when they affect included downstream work.
    """
    disabled = set(disabled_steps)
    return any(record.step not in disabled and not (
        is_branch(record.path) and {cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE} <= disabled)
               for record in overwrite_dependents(records, overwritten))


def rebuild_sources(records: Sequence[ArtifactRecord],
                    states: Sequence[ExperimentState],
                    overwritten: Iterable[str],
                    ) -> tuple[set[str], bool]:
    """
    Identify rebuild starting steps and whether original acquisitions are needed.
    """
    from_original = any(record.legacy for record in records) or any(state.compacted for state in states)
    sources: set[str] = ({cst.StepName.CONVERT} if from_original else
                        set(overwritten) | {record.step for record in records if record.problem and record.step})
    return sources, from_original


def downstream_steps(sources: Iterable[str]) -> tuple[str, ...]:
    """
    Return affected later steps in order, keeping the two analyses independent.
    """
    chain = cst.WORKFLOW_ORDER
    result: set[str] = set()
    for source in sources:
        if source in (cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE):
            continue
        if source in chain:
            result.update(chain[chain.index(source) + 1:])
    return tuple(step for step in chain if step in result)
