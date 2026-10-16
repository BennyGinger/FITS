"""Publish rewritten FITS settings and tables with per-file atomic replacement."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd


def atomic_table(data: pd.DataFrame, path: Path) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".parquet")
    os.close(fd)
    temporary = Path(name)
    try:
        data.to_parquet(temporary, index=False)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_bytes(path: Path, payload: bytes) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=path.suffix)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
