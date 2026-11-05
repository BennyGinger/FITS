"""Run-wide file actions and compacting; processing requires its own plan."""

from __future__ import annotations
from collections.abc import Callable
from pathlib import Path
from fits.workflows.file_management.relocation import PortablePlan, plan_portable_update, apply_portable_update
from fits.workflows.experiments import ExperimentState
from fits.workflows.checks.locations import inspect_locations
from fits.workflows.checks.compatibility import inspect_run_compatibility, require_current_run
from . import rebuild
from .rebuild import ProcessingPlan
from .compaction import CompactionPlan, apply_compaction, can_compact, compact_run, plan_compaction


def plan_migration(root: Path) -> PortablePlan | None:
    """
    Return a reviewed metadata/layout migration, or None when already current.
    """
    status = inspect_run_compatibility(root)
    if not status.outdated:
        return None
    return plan_portable_update(root, upgrade=True, migrate=True)


def migrate(plan: PortablePlan) -> tuple[ExperimentState, ...]:
    """
    Migrate existing results. This function never launches processing.
    """
    if not plan.migrate:
        raise ValueError('Expected a migration plan.')
    return apply_portable_update(plan)


def plan_update(root: Path) -> PortablePlan | None:
    """
    Use the same relocation/table executor for already migrated experiments.
    """
    require_current_run(root)
    if not inspect_locations(root).needs_update:
        return None
    return plan_portable_update(root)


def update(plan: PortablePlan) -> tuple[ExperimentState, ...]:
    """
    Return the current update.
    """
    if plan.migrate or plan.rebuild:
        raise ValueError('Use the migration or processing action for this plan.')
    return apply_portable_update(plan)


def plan_downstream_update(root: Path) -> ProcessingPlan | None:
    """
    Plan downstream update.
    """
    require_current_run(root)
    return rebuild.plan_downstream_update(root)


def plan_full_rebuild(root: Path) -> ProcessingPlan | None:
    """
    Review a complete rebuild, retaining a backup before replacing results.
    """
    require_current_run(root)
    return rebuild.plan_full_rebuild(root)


def plan_required_rebuild(root: Path) -> ProcessingPlan | None:
    """
    Plan only complete reconstruction or stale results that need rebuilding.
    """
    require_current_run(root)
    return rebuild.plan_required_rebuild(root)


def update_downstream(plan: ProcessingPlan, run: Callable[[ProcessingPlan], None]) -> None:
    """
    Execute only an explicitly reviewed processing plan through GUI or CLI.
    """
    rebuild.execute_plan(plan, run)
