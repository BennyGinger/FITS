"""Estimate the pending configured pipeline before any processing begins."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fits.environment import constant as cst
from fits.workflows.checks.space import require_processing_space
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState
from fits.workflows.file_management.migration import checkpoint_complete
from fits.workflows.runtime.run_decision import decide_run


def _pending_outputs(state: ExperimentState, config: Mapping[str, Any]) -> int:
    """
    Count enabled unfinished or overwritten outputs within the reviewed scope.
    """
    count = 0
    for step in cst.WORKFLOW_ORDER:
        entry = config.get(step, {})
        if not entry.get('enabled'):
            continue
        if state.execution_scope is not None and step not in state.execution_scope.get(state.workdir, ()):
            continue
        profile = REGISTRY[step].profile
        overwrite = entry.get('params', {}).get('overwrite', False)
        if checkpoint_complete(state, profile, overwrite):
            continue
        if not decide_run(state, profile, overwrite).is_complete:
            count += 1
    return count


def require_pipeline_space(root: Path,
                           states: Sequence[ExperimentState],
                           config: Mapping[str, Any],
                           *,
                           additional_bytes: int = 0,
                           ) -> None:
    """
    Reject a run that cannot fit its estimated pending pipeline outputs.
    """
    require_processing_space(root, ((state, _pending_outputs(state, config)) for state in states),
                             additional_bytes=additional_bytes)
