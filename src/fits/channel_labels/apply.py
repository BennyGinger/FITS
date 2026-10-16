"""Apply a validated rename with stale-preview checks and rollback."""

from __future__ import annotations

import os
import shutil
import tempfile
from copy import deepcopy
from collections.abc import Callable, Mapping
from pathlib import Path

from fits_io import FitsIO

from fits.channel_labels.discovery import _fingerprint, files_to_update, validate_labels
from fits.channel_labels.documents import (rename_workflow_meta, rename_table,
                                           render_settings, render_state)
from fits.channel_labels.lock import run_write_guard
from fits.channel_labels.model import LabelPlan
from fits.channel_labels.persistence import atomic_bytes, atomic_table


def apply_labels(plan: LabelPlan, proposed: Mapping[int, str],
                 progress: Callable[[int, int, Path], None] | None = None) -> tuple[Path, ...]:
    """Apply a validated rename, restoring completed files if a later file fails."""
    with run_write_guard(plan.run_dir):
        return _apply_unlocked(plan, proposed, progress)


def _apply_unlocked(plan: LabelPlan, proposed: Mapping[int, str],
                    progress: Callable[[int, int, Path], None] | None) -> tuple[Path, ...]:
    labels = validate_labels(plan, proposed)
    targets = files_to_update(plan, labels)
    if not targets:
        return ()
    for path, fingerprint in plan.fingerprints:
        if _fingerprint(path) != fingerprint:
            raise RuntimeError(f"{path} changed since inspection. Inspect the run again.")
    mapping = {old: labels[index] for index, old in plan.labels}
    updated: list[Path] = []
    # Hard links keep large image backups cheap on local filesystems. On shares
    # without hard-link support, make a real copy before changing anything.
    backup_root = Path(tempfile.mkdtemp(prefix="fits_labels_", dir=plan.run_dir))
    backups: dict[Path, Path] = {}
    preserve_backups = False
    try:
        for number, path in enumerate(targets):
            backup = backup_root / str(number)
            try:
                os.link(path, backup)
            except OSError:
                shutil.copy2(path, backup)
            backups[path] = backup
        total = len(targets)
        for number, path in enumerate(targets, 1):
            updated.append(path)
            try:
                if path in plan.tiffs:
                    reader = FitsIO.from_path(path)
                    new = [labels[index] for index in reader.artifact_channel_indices]
                    custom = deepcopy(dict(reader.metadata.custom_metadata))
                    rename_workflow_meta(custom, mapping)
                    if new != reader.channel_labels or custom != reader.metadata.custom_metadata:
                        reader.set_channel_labels(new, custom_metadata=custom)
                elif path in plan.tables:
                    atomic_table(rename_table(path, mapping), path)
                elif path in plan.settings:
                    atomic_bytes(path, render_settings(path, mapping))
                else:
                    atomic_bytes(path, render_state(path, mapping))
            except Exception as error:
                raise RuntimeError(f"Could not update {path}: {error}") from error
            if progress:
                progress(number, total, path)
    except Exception as error:
        failed_restores = []
        for path in reversed(updated):
            try:
                os.replace(backups[path], path)
            except OSError as restore_error:
                failed_restores.append(f"{path}: {restore_error}")
        if failed_restores:
            preserve_backups = True
            raise RuntimeError(
                f"Rename failed: {error}. Backups are in {backup_root}; "
                f"restoration failed for: {'; '.join(failed_restores)}") from error
        raise
    else:
        return tuple(updated)
    finally:
        if not preserve_backups:
            shutil.rmtree(backup_root, ignore_errors=True)
