"""Publish rewritten FIScH settings and tables with per-file atomic replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
import os
import tempfile
import pandas as pd
from pathlib import Path
import json
from fisch.workflows.artifacts.provenance import PARQUET_PROVENANCE_KEY
from fisch.channel_labels.documents import rename_workflow_meta
from fisch.environment import naming


def atomic_table(data: pd.DataFrame,
                 path: Path,
                 *,
                 mapping: Mapping[str, str] | None = None,
                 metadata_transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 ) -> None:
    """
    Atomic table.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".parquet")
    os.close(fd)
    temporary = Path(name)
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pa.Table.from_pandas(data, preserve_index=False)
        metadata = dict(pq.read_schema(path).metadata or {})
        metadata.update(table.schema.metadata or {})
        if naming.LEGACY_PARQUET_ARTIFACT in metadata:
            metadata.setdefault(PARQUET_PROVENANCE_KEY, metadata.pop(naming.LEGACY_PARQUET_ARTIFACT))
        if naming.LEGACY_PARQUET_MEMBERSHIP in metadata:
            metadata.setdefault(naming.PARQUET_MEMBERSHIP, metadata.pop(naming.LEGACY_PARQUET_MEMBERSHIP))
        if mapping and PARQUET_PROVENANCE_KEY in metadata:
            payload = json.loads(metadata[PARQUET_PROVENANCE_KEY])
            rename_workflow_meta(payload, mapping)
            metadata[PARQUET_PROVENANCE_KEY] = json.dumps(payload).encode()
        if metadata_transform:
            payload = json.loads(metadata.get(PARQUET_PROVENANCE_KEY, b'{}'))
            metadata[PARQUET_PROVENANCE_KEY] = json.dumps(metadata_transform(payload)).encode()
        pq.write_table(table.replace_schema_metadata(metadata), temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_bytes(path: Path, payload: bytes) -> None:
    """
    Atomic bytes.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=path.suffix)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
