"""Inspect run structure and metadata compatibility before processing or migration."""

from __future__ import annotations

import json
from pathlib import Path

from fits.environment import constant as cst
from fits.environment.paths import is_internal_path
from fits.workflows.artifacts.provenance import compatible, read_metadata
from fits.workflows.checks.models import RunCompatibility
from fits.workflows.experiments import active_states, discover_saved_states


def inspect_run_compatibility(root: Path) -> RunCompatibility:
    """
    Inventory format and layout problems that make the whole run read-only.
    """
    root = root.expanduser().resolve()
    states = tuple(discover_saved_states(root))
    old_states = tuple(path for path in root.rglob('experiment_state.json') if not is_internal_path(path, root))
    files = tuple(sorted({path for name in cst.MANAGED_NAMES for path in root.rglob(name)
                          if not is_internal_path(path, root) and path.is_file()}))
    problems = [f'Old experiment layout: {path.parent.relative_to(root)}' for path in old_states]
    outdated_folders = {path.parent for path in old_states}
    if (root / '.fits/upgrade_pending.json').is_file():
        problems.append('An experiment upgrade needs to finish rebuilding. Resume it through Manage files.')
        pending = root / '.fits/upgrade_pending.json'
        try:
            outdated_folders.update(root / path for path in json.loads(pending.read_text()).get('required_steps',
                                                                                                {},
                                                                                                ))
        except (OSError, ValueError):
            outdated_folders.update(state.workdir for state in states)
    excluded = {state.workdir for state in states if state.excluded}
    for state in active_states(states):
        local_original = state.workdir.parent / state.original_image.name
        if state.workdir.parent != state.original_image.parent and not local_original.is_file():
            problems.append(f'Acquisition grouping needs updating: {state.workdir}')
            outdated_folders.add(state.workdir)
    for path in files:
        if path.parent in excluded:
            continue
        try:
            if not compatible(read_metadata(path)):
                problems.append(f'Older/incompatible artifact: {path.relative_to(root)}')
                outdated_folders.add(path.parent)
        except Exception as error:
            problems.append(f'Cannot verify {path.relative_to(root)}: {error}')
            outdated_folders.add(path.parent)
    owners = {state.workdir for state in states} | {path.parent for path in old_states}
    for folder in sorted({path.parent for path in files if path.parent not in owners}):
        problems.append(f'Processed files have no active experiment state: {folder.relative_to(root)}. Manage files must resolve their acquisition before processing.')
        outdated_folders.add(folder)
    return RunCompatibility(root, states, old_states, files, tuple(problems), tuple(sorted(outdated_folders)))


def require_current_run(root: Path) -> None:
    """
    Reject processing or compacting until run compatibility problems are resolved.
    """
    status = inspect_run_compatibility(root)
    if status.outdated:
        raise ValueError('This entire run is outdated/read-only. Use Manage files to migrate it before processing or compacting.\n' + status.describe())
