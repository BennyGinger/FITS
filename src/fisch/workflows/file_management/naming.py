"""Plan complete current-name adoption without changing retained backup contents."""

from __future__ import annotations

from pathlib import Path

from fisch.environment import naming
from fisch.workflows.file_management.transactions import FileUpdate


def is_history(path: Path, root: Path) -> bool:
    """
    Exclude retained snapshots and transaction workspaces from active discovery.
    """
    parts = path.relative_to(root).parts
    return any(part in naming.INTERNAL_DIRECTORIES for part in parts) and any(
        part in naming.HISTORY_DIRECTORIES or part.startswith('file_update_') for part in parts)


def legacy_paths(root: Path) -> tuple[Path, ...]:
    """
    Find active legacy files and metadata containers, leaving backups inspectable.
    """
    return tuple(path for path in root.rglob('*') if not is_history(path, root)
                 and naming.is_legacy_name(path.name)
                 and (path.is_file() or path.is_dir() and any(path.iterdir())))


def plan_name_moves(root: Path) -> tuple[tuple[Path, Path], ...]:
    """
    Rename files before their metadata parents, merging partial containers safely.
    """
    paths = legacy_paths(root)
    moves: list[tuple[Path, Path]] = []
    destinations: set[Path] = set()

    def add(source: Path, target: Path) -> None:
        """
        Reject ambiguous target collisions before any active files are changed.
        """
        if target.exists() or target in destinations:
            raise ValueError(f'Migration destination already exists: {target}. No files changed.')
        destinations.add(target)
        moves.append((source, target))

    for path in sorted(paths):
        if path.is_file():
            add(path, path.with_name(naming.canonical_name(path.name)))

    def merge_directory(source: Path, target: Path) -> None:
        """
        Keep existing current containers while moving only missing legacy entries.
        """
        if not target.exists() and source != root / naming.LEGACY_RUN_METADATA:
            add(source, target)
            return
        for child in sorted(source.iterdir()):
            if child.name == 'run_write.lock':
                continue
            new_name = naming.canonical_name(child.name)
            moved_child = source / new_name if child.is_file() and child in paths else child
            destination = target / new_name
            if child.is_dir() and destination.is_dir():
                merge_directory(child, destination)
            else:
                add(moved_child, destination)

    directories = sorted((path for path in paths if path.is_dir()), key=lambda path: len(path.parts), reverse=True)
    for directory in directories:
        merge_directory(directory, directory.with_name(naming.canonical_name(directory.name)))
    return tuple(moves)


def retire_legacy_containers(root: Path, transaction: FileUpdate) -> None:
    """
    Retire emptied old metadata containers reversibly after their contents move.
    """
    directories = [path for path in root.rglob('*') if path.is_dir()
                   and path.name in (naming.LEGACY_RUN_METADATA, naming.LEGACY_ACQUISITION_METADATA)
                   and not is_history(path, root)]
    index = 0
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        lock = directory / 'run_write.lock'
        if lock.is_file():
            transaction.move(lock, transaction.backup / f'legacy_lock_{index}')
            index += 1
        children = sorted((path for path in directory.rglob('*') if path.is_dir()),
                          key=lambda path: len(path.parts), reverse=True)
        for child in [*children, directory]:
            if child.exists() and not any(child.iterdir()):
                transaction.move(child, transaction.backup / f'legacy_empty_{index}')
                index += 1
