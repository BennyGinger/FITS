"""Shared disk-space estimates for pipeline and file-management operations."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import shutil

from fisch.environment import constant as cst
from fisch.workflows.experiments import ExperimentState


def file_bytes(paths: Iterable[Path]) -> int:
    """
    Sum existing distinct files without following copied symbolic links.
    """
    return sum(path.lstat().st_size for path in set(paths) if path.is_file() or path.is_symlink())


def require_processing_space(root: Path,
                             workloads: Iterable[tuple[ExperimentState, int]],
                             *,
                             additional_bytes: int = 0,
                             ) -> None:
    """
    Estimate pending outputs as raw/final array size multiplied by output count.
    """
    required = additional_bytes
    for state, count in workloads:
        if count == 0:
            continue
        candidates = (state.artifact(cst.ARTI_IMG_RAW), state.artifact(cst.ARTI_IMG), state.original_image)
        source = next((path for path in candidates if path is not None and path.is_file()), None)
        if source is not None:
            required += source.stat().st_size * count
    require_free_space(root, required, action='run the requested processing')


def require_free_space(root: Path, required: int, *, action: str) -> None:
    """
    Reject an operation that cannot fit its estimated outputs and working space.
    """
    if required:
        required += max(16 * 1024**2, required // 100)
    available = shutil.disk_usage(root).free
    if available < required:
        raise ValueError(f'Not enough disk space to {action}. Estimated space needed: '
                         f'{required / 1024**3:.2f} GiB ({required:,} bytes); '
                         f'available: {available / 1024**3:.2f} GiB ({available:,} bytes). '
                         'Free space or move the run to a larger disk, then try again. '
                         'No experiment files have been changed by this action.')
