"""Retain a coherent result/state snapshot before an approved older-format rebuild."""

from __future__ import annotations

from fisch.workflows.checks.models import PreflightReport
from datetime import datetime, timezone
from pathlib import Path
import shutil
from fisch.environment import constant as cst
from fisch.environment.paths import experiment_backup, experiment_state_path
from fisch.workflows.artifacts.branch_masks import is_branch
from fisch.workflows.experiments.persistence import STATE_FILENAME
from fisch.workflows.file_management.transactions import FileUpdate
from fisch.workflows.checks.space import file_bytes, require_free_space
from fisch.workflows.experiments import ExperimentState
from collections.abc import Mapping, Sequence
from fisch.workflows.definitions.registry import REGISTRY


def replacement_states(states: Sequence[ExperimentState], scope: Mapping[Path, Sequence[str]]) -> list[ExperimentState]:
    """
    Select experiments whose scheduled numerical outputs will replace existing files.
    """
    return [state for state in states if any(
        (path := state.artifact(REGISTRY[step].profile.output_artifact)) is not None and path.is_file()
        for step in scope.get(state.workdir, ()))]


def rebuild_backup_size(states: Sequence[ExperimentState]) -> int:
    """
    Estimate complete affected-folder copies plus their matching experiment states.
    """
    return file_bytes(path for state in states
                      for path in (*state.workdir.rglob('*'), experiment_state_path(state.workdir)))


def retain_rebuild_backups(root: Path, states: Sequence[ExperimentState]) -> None:
    """
    Copy affected experiment folders and state before numerical replacement.
    """
    revision = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    with FileUpdate(root) as transaction:
        for index, state in enumerate(states):
            staged = transaction.backup / f'experiment_{index}'
            shutil.copytree(state.workdir, staged, symlinks=True)
            shutil.copy2(experiment_state_path(state.workdir), staged / STATE_FILENAME)
            transaction.move(staged, experiment_backup(state.workdir) / revision)


def preserve_replaced_results(report: PreflightReport) -> None:
    """
    Retain the output/state set before rebuilding incompatible earlier results.
    """
    revision = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if not report.states:
        raise ValueError('Cannot retain older results without matching experiment states.')
    root = report.states[0].run_dir or report.states[0].original_image.parent
    copied = [experiment_state_path(state.workdir) for state in report.states]
    copied.extend(path for state in report.states for path in state.workdir.glob('*') if is_branch(path))
    require_free_space(root, file_bytes(copied), action='retain earlier results before rebuilding')
    with FileUpdate(root) as transaction:
        for state in report.states:
            folder = experiment_backup(state.workdir) / revision
            transaction.parents(folder)
            path = experiment_state_path(state.workdir)
            if path.is_file():
                target = folder / STATE_FILENAME
                transaction.protect(target)
                shutil.copy2(path, target)
            # The rebuild replaces this result set, including any compatible
            # intermediates. Keeping the full set makes restoration coherent.
            for name in cst.MANAGED_NAMES:
                path = state.workdir / name
                if path.is_file():
                    transaction.move(path, folder / name)
            # Manual branch drawings stay active and also accompany the snapshot.
            for template in (cst.REFERENCE_TEMPLATE, cst.ROI_TEMPLATE):
                for path in state.workdir.glob(template.format(label='*')):
                    if path.is_file():
                        target = folder / path.name
                        transaction.protect(target)
                        shutil.copy2(path, target)
