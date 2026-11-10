"""Explicit review/restore/delete of retained experiment history."""

from __future__ import annotations

from collections.abc import Sequence
from fisch.workflows.experiments import ExperimentState, discover_saved_states, save_experiment_state
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from fisch.environment import constant as cst
from fisch.environment.paths import BACKUP_DIR_NAME, RUN_METADATA_DIR_NAME, ACQUISITION_METADATA_DIR_NAME, experiment_backup, experiment_state_path
from fisch.channel_labels.lock import run_write_guard
from fisch.workflows.experiments.serialization import deserialize_experiment_state
from fisch.workflows.file_management.transactions import FileUpdate
from fisch.workflows.file_management.run_history import RUN_SNAPSHOT_MARKER, restore_run_snapshot
from fisch.workflows.checks.space import require_free_space
from fisch.workflows.artifacts.branch_masks import is_branch


@dataclass(frozen=True)
class Snapshot:
    directory: Path
    series: Path
    files: tuple[Path, ...]
    fingerprints: tuple[tuple[Path, int, int], ...]

    @property
    def whole_run(self) -> bool:
        """
        Return whether restoring this snapshot exchanges the complete run folder.
        """
        return (self.directory / RUN_SNAPSHOT_MARKER).is_file()

    @property
    def reason(self) -> str:
        """
        Explain which file-management operation retained this backup.
        """
        marker = self.directory / RUN_SNAPSHOT_MARKER
        if not marker.is_file():
            return 'Before rebuilding'
        reason = json.loads(marker.read_text(encoding='utf-8')).get('reason')
        return {'migration': 'Before migration to FIScH 5', 'update': 'Before updating files',
                'restore': 'Before restoration'}.get(reason, 'Retained run')

    @property
    def size(self) -> int:
        """
        Return the retained data size.
        """
        return sum(size for path, size, modified in self.fingerprints)


def snapshots(root: Path, selected: Path | None = None) -> tuple[Snapshot, ...]:
    """
    Return the current snapshots.
    """
    root = Path(root).resolve()
    result = []
    selected = Path(selected).resolve() if selected else root
    if selected.is_file():
        selected = selected.parent
    folders = [(directory, directory.parents[3] / directory.parent.name)
               for category in (BACKUP_DIR_NAME, 'legacy')
               for directory in root.glob(f'**/{ACQUISITION_METADATA_DIR_NAME}/{category}/*/*')]
    # Reading/managing old history belongs at this explicit compatibility boundary.
    folders += [(directory, directory.parents[2]) for category in (BACKUP_DIR_NAME, 'legacy')
                for directory in root.glob(f'**/{RUN_METADATA_DIR_NAME}/{category}/*')
                if ACQUISITION_METADATA_DIR_NAME not in directory.relative_to(root).parts]
    for directory, series in sorted(folders):
        if not directory.is_dir() or directory.is_symlink():
            continue
        if any((parent / RUN_SNAPSHOT_MARKER).is_file() for parent in directory.parents):
            continue
        whole_run = (directory / RUN_SNAPSHOT_MARKER).is_file()
        if not whole_run and not (series == selected or selected in series.parents):
            continue
        files = tuple(path for path in sorted(directory.rglob('*')) if path.is_file())
        if not files:
            continue
        result.append(Snapshot(directory,
                               series,
                               files,
                               tuple((path, path.stat().st_size, path.stat().st_mtime_ns) for path in files),
                               ))
    return tuple(result)


def verify_snapshot(snapshot: Snapshot) -> None:
    """
    Verify snapshot.
    """
    actual = {path for path in snapshot.directory.rglob('*') if path.is_file()}
    if actual != set(snapshot.files):
        raise ValueError('History changed after preview. Review it again.')
    for path, size, modified in snapshot.fingerprints:
        if (path.stat().st_size, path.stat().st_mtime_ns) != (size, modified):
            raise ValueError(f'History changed after preview: {path}')


def delete_history(root: Path, entries: Sequence[Snapshot]) -> None:
    """
    Delete history.
    """
    with run_write_guard(root):
        for entry in entries:
            verify_snapshot(entry)
        require_free_space(root, 0, action='delete retained history')
        with FileUpdate(root) as transaction:
            for index, entry in enumerate(entries):
                transaction.move(entry.directory, transaction.backup / f'delete_{index}')


def restore_history(root: Path, entry: Snapshot) -> ExperimentState | None:
    """
    Restore a complete run folder or exchange a per-series output/state snapshot.
    """
    if entry.whole_run:
        with run_write_guard(root):
            verify_snapshot(entry)
            restore_run_snapshot(root, entry.directory)
        return None
    snapshot_state = entry.directory / 'experiment_state.json'
    if not snapshot_state.is_file():
        raise ValueError('This snapshot has no matching experiment state; it cannot be restored safely.')
    raw = json.loads(snapshot_state.read_text(encoding='utf-8'))
    current = next((state for state in discover_saved_states(root) if state.workdir == entry.series), None)
    if current is None:
        raise ValueError('The active series state is missing. Restore requires its matching acquisition.')
    parsed = deserialize_experiment_state(raw)
    artifacts = {}
    for kind, stored in parsed['artifacts'].items():
        target = current.original_image if kind == cst.ARTI_RAW else entry.series / stored.name
        artifacts[kind] = Path(os.path.relpath(target, entry.series))
    restored = ExperimentState(workdir=entry.series, run_dir=Path(root), **{**parsed, 'artifacts': artifacts, 'excluded': current.excluded})
    restored_files = [path for path in entry.files if path.name in cst.MANAGED_NAMES or is_branch(path)]
    if not restored_files:
        raise ValueError('The snapshot contains no recognized processing outputs.')
    require_free_space(root, 2 * snapshot_state.stat().st_size, action='restore retained results')
    for kind, stored in artifacts.items():
        if kind == cst.ARTI_RAW:
            continue
        name = stored.name
        # Compacted states may retain absent historical stage paths by design.
        if name in (cst.ARRAY_NAME, cst.MASKS_COMPACTED) or kind in (cst.ARTI_IMG, cst.ARTI_TRACK, cst.ARTI_SEG):
            if not any(path.name == name for path in restored_files):
                raise ValueError(f'Snapshot is incomplete: {name}')
    revision = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = experiment_backup(entry.series) / revision
    with run_write_guard(root):
        verify_snapshot(entry)
        with FileUpdate(root) as transaction:
            transaction.move(experiment_state_path(entry.series), destination / 'experiment_state.json')
            for name in cst.MANAGED_NAMES:
                path = entry.series / name
                if path.is_file():
                    transaction.move(path, destination / name)
            for template in (cst.REFERENCE_TEMPLATE, cst.ROI_TEMPLATE):
                for path in entry.series.glob(template.format(label='*')):
                    if path.is_file():
                        transaction.move(path, destination / path.name)
            for path in restored_files:
                transaction.move(path, entry.series / path.name)
            transaction.move(snapshot_state, experiment_state_path(entry.series))
            transaction.protect(experiment_state_path(entry.series))
            save_experiment_state(restored)
            # Masters must never describe the replaced active set.
            for name in ('master_quantification.parquet', 'master_distance_profile.parquet'):
                path = Path(root) / name
                if path.is_file():
                    transaction.move(path, destination / name)
    return restored
