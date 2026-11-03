"""Retain and restore complete run folders without reconstructing old metadata."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from fits.environment.paths import BACKUP_DIR_NAME, FITS_DIR_NAME, backups_dir
from fits.workflows.file_management.transactions import FileUpdate
from fits.workflows.checks.space import file_bytes, require_free_space


RUN_SNAPSHOT_MARKER = 'run_snapshot.json'
RUN_CONTENTS = 'run'


def require_run_backup_space(root: Path, rewrite_paths: Iterable[Path]) -> None:
    """
    Reject migration when its retained copy and rewrite workspace cannot fit.
    """
    backup_bytes = 0
    for item in _run_items(root):
        paths = item.rglob('*') if item.is_dir() and not item.is_symlink() else (item,)
        backup_bytes += file_bytes(paths)
    require_free_space(root, backup_bytes + 2 * file_bytes(rewrite_paths), action='retain the run backup and update files')


def _write_marker(directory: Path, reason: str) -> None:
    """
    Identify a complete run snapshot separately from per-series result history.
    """
    (directory / RUN_SNAPSHOT_MARKER).write_text(json.dumps({'reason': reason}), encoding='utf-8')


def stage_run_snapshot(root: Path, transaction: FileUpdate, *, reason: str) -> Path:
    """
    Copy the unchanged run into transaction storage, excluding retained history.
    """
    staged = transaction.backup / 'run_snapshot'
    staged.mkdir()

    def _ignore_history(directory: str, names: list[str]) -> set[str]:
        """
        Exclude root history and transaction storage to prevent recursive copies.
        """
        if Path(directory) == root / FITS_DIR_NAME:
            return {name for name in names if name in {BACKUP_DIR_NAME, 'legacy', 'run_write.lock'} or name.startswith('file_update_')}
        return set()

    shutil.copytree(root, staged / RUN_CONTENTS, symlinks=True, ignore=_ignore_history)
    _write_marker(staged, reason)
    return staged


def publish_run_snapshot(root: Path, staged: Path, transaction: FileUpdate) -> Path:
    """
    Retain a staged folder after successful migration or restoration.
    """
    revision = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = backups_dir(root) / revision
    transaction.move(staged, destination)
    return destination


def _run_items(root: Path) -> Iterable[Path]:
    """
    Yield run contents while keeping root history and active transactions in place.
    """
    for path in sorted(root.iterdir()):
        if path.name != FITS_DIR_NAME:
            yield path
        else:
            for child in sorted(path.iterdir()):
                if child.name not in {BACKUP_DIR_NAME, 'legacy', 'run_write.lock'} and not child.name.startswith('file_update_'):
                    yield child


def restore_run_snapshot(root: Path, directory: Path) -> None:
    """
    Exchange complete run folders under the caller's write guard, retaining both.
    """
    contents = directory / RUN_CONTENTS
    if not contents.is_dir():
        raise ValueError('The retained run folder is missing; restoration cannot proceed.')
    require_free_space(root, 4096, action='restore the retained run')
    with FileUpdate(root) as transaction:
        outgoing = transaction.backup / 'run_snapshot'
        outgoing.mkdir()
        _write_marker(outgoing, 'restore')
        for path in _run_items(root):
            transaction.move(path, outgoing / RUN_CONTENTS / path.relative_to(root))
        for path in _run_items(contents):
            transaction.move(path, root / path.relative_to(contents))
        publish_run_snapshot(root, outgoing, transaction)
        transaction.move(directory, transaction.backup / 'restored_snapshot')
