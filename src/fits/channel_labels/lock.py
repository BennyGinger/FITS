"""Shared run-directory guard for pipeline writes and channel-label changes."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from fits.environment.paths import ensure_fits_directory, fits_dir


@contextmanager
def run_write_guard(run_dir: Path):
    """Allow one FITS writer at a time for a run directory.

    The GUI and CLI pipeline entry points hold this file lock for the entire
    run. Channel-label inspection and saving use the same lock, so a separate
    process cannot rename metadata while the pipeline is producing artifacts.
    The lock lives in ``<run_dir>/.fits/run_write.lock`` and is released when
    the context exits, including after an error. A busy run raises immediately.
    """
    lock_path = fits_dir(run_dir) / "run_write.lock"
    ensure_fits_directory(lock_path.parent)
    lock = FileLock(str(lock_path), timeout=0)
    try:
        with lock:
            yield
    except Timeout as error:
        raise RuntimeError(f"A FITS pipeline or channel-label update is already active in {run_dir}.") from error
