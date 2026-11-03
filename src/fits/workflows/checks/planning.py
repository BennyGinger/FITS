"""Shared workflow ordering and rebuild-source selection for preflight checks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from fits.environment import constant as cst
from fits.workflows.checks.models import ArtifactRecord
from fits.workflows.experiments import ExperimentState


def overwrite_steps(config: Mapping[str, Any]) -> tuple[cst.StepName, ...]:
    """
    Return enabled overwrite requests in workflow order.
    """
    return tuple(step for step in cst.WORKFLOW_ORDER
                 if config.get(step, {}).get("enabled") and config[step].get("params", {}).get("overwrite"))


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
