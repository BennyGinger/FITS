"""Restore raw acquisitions and remove FIScH-owned data from an entire run."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from fisch.channel_labels.lock import run_write_guard
from fisch.environment import constant as cst
from fisch.environment.paths import ACQUISITION_METADATA_DIR_NAME, INTERNAL_DIR_NAMES, STATE_FILENAME
from fisch.settings.loader import SAVED_SETTINGS_NAME
from fisch.workflows.artifacts.branch_masks import is_branch
from fisch.workflows.experiments.discovery import collect_supported_files
from fisch.workflows.experiments.model import ExperimentState
from fisch.workflows.experiments.serialization import deserialize_experiment_state


@dataclass(frozen=True)
class ResetPlan:
    """
    Describe validated raw moves, generated files, and removable metadata.
    """
    root: Path
    moves: tuple[tuple[Path, Path], ...]
    files: tuple[Path, ...]
    metadata: tuple[Path, ...]
    folders: tuple[Path, ...]


def _inside_run(path: Path, root: Path) -> None:
    """
    Reject paths outside the run and links that could redirect destructive work.
    """
    if not path.resolve().is_relative_to(root):
        raise ValueError(f'Reset cannot access a path outside the run: {path}')
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            raise ValueError(f'Reset cannot follow symbolic links: {candidate}')


def _owned_file(path: Path) -> bool:
    """
    Identify reserved FIScH output names, including legacy results and drawings.
    """
    return (path.name in {*cst.MANAGED_NAMES, *(name for _, name in cst.MASTER_TABLES),
                          STATE_FILENAME, SAVED_SETTINGS_NAME}
            or is_branch(path)
            or path.name.startswith(cst.TRACK_OVERLAY_PREFIX)
            or any(path.match(f'.{name}.centroids-*.npz') for name in cst.MASK_NAMES))


def _reset_state(path: Path, root: Path) -> ExperimentState:
    """
    Load a current or legacy state and verify its series and original before removal.
    """
    _inside_run(path, root)
    raw = json.loads(path.read_text(encoding='utf-8'))
    acquisition = path.parents[3] if ACQUISITION_METADATA_DIR_NAME in path.relative_to(root).parts else None
    workdir = (acquisition / raw['series_path'] if acquisition is not None else path.parent).resolve()
    _inside_run(workdir, root)
    state = ExperimentState(workdir=workdir, **deserialize_experiment_state(raw))
    _inside_run(state.original_image, root)
    if not state.original_image.is_file():
        raise ValueError(f'Reset stopped: original acquisition is missing: {state.original_image}')
    return state


def plan_reset(root: Path) -> ResetPlan:
    """
    Check all originals and destinations before allowing irreversible removal.
    """
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'Run directory does not exist: {root}')
    paths = sorted(root.rglob('*'))
    active = [path for path in paths
              if not any(part in INTERNAL_DIR_NAMES for part in path.relative_to(root).parts[:-1])]
    metadata = tuple(path for path in active if path.name in INTERNAL_DIR_NAMES)
    for path in metadata:
        _inside_run(path, root)
        if not path.is_dir():
            raise ValueError(f'Expected a FIScH metadata directory: {path}')
    originals = set(collect_supported_files(root))
    generated = {path for path in active if path.is_file() and _owned_file(path)}
    folders: set[Path] = set()
    state_paths = [path for path in active if path.name == STATE_FILENAME]
    for directory in metadata:
        if directory.name == ACQUISITION_METADATA_DIR_NAME:
            state_paths.extend(directory.glob(f'experiment_state/*/{STATE_FILENAME}'))
    for path in state_paths:
        state = _reset_state(path, root)
        originals.add(state.original_image.resolve())
        folders.add(state.workdir)
        for kind in state.artifacts:
            output = state.artifact(kind)
            if kind != cst.ARTI_RAW and output is not None:
                _inside_run(output, root)
                if output.is_file():
                    generated.add(output.resolve())
    moves: list[tuple[Path, Path]] = []
    for directory in metadata:
        if directory.name != ACQUISITION_METADATA_DIR_NAME:
            continue
        acquisition = directory.parent
        local = sorted(path for path in originals if path.parent == acquisition)
        if not local:
            raise ValueError(f'Reset stopped: no original acquisition found in {acquisition}')
        if acquisition != root:
            moves.extend((source, acquisition.parent / source.name) for source in local)
            folders.add(acquisition)
    if generated and not originals:
        raise ValueError('Reset stopped: FIScH results exist but no original acquisitions were found.')
    destinations: set[Path] = set()
    for source in originals:
        _inside_run(source, root)
        if any(source.is_relative_to(directory) for directory in metadata):
            raise ValueError(f'Reset cannot remove metadata containing an original: {source}')
    for source, target in moves:
        _inside_run(target, root)
        if target.exists() or target.is_symlink() or target in destinations:
            raise ValueError(f'Reset stopped: raw destination already exists or is ambiguous: {target}')
        destinations.add(target)
    generated.difference_update(originals)
    for path in generated:
        _inside_run(path, root)
        folders.add(path.parent)
    # Only remove empty generated directories; unrelated user files keep their folders.
    removable = {parent for folder in folders for parent in (folder, *folder.parents)
                 if parent != root and parent.is_relative_to(root)}
    return ResetPlan(root, tuple(moves), tuple(sorted(generated)), metadata,
                     tuple(sorted(removable, key=lambda path: len(path.parts), reverse=True)))


def _apply_reset(plan: ResetPlan) -> None:
    """
    Move validated originals before removing outputs, metadata, and empty folders.
    """
    for source, target in plan.moves:
        source.rename(target)
    for path in plan.files:
        path.unlink()
    for directory in plan.metadata:
        if directory == plan.root / '.pipeline':
            for child in directory.iterdir():
                if child.name != 'run_write.lock':
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
        else:
            shutil.rmtree(directory)
    for folder in plan.folders:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()


def reset_run(root: Path) -> None:
    """
    Validate under the shared writer guard, then reset without creating a backup.
    """
    root = root.expanduser().resolve()
    with run_write_guard(root):
        plan = plan_reset(root)
        try:
            _apply_reset(plan)
        except OSError as error:
            raise RuntimeError('Reset did not finish. Some FIScH files may already have been removed; '
                               'these removals cannot be undone. Original acquisitions are preserved '
                               f'in their existing or restored locations under {root}.\n\n{error}') from error
    lock = root / '.pipeline/run_write.lock'
    lock.unlink(missing_ok=True)
    if lock.parent.is_dir() and not any(lock.parent.iterdir()):
        lock.parent.rmdir()
