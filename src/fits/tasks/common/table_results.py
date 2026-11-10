from __future__ import annotations

from scope_io.metadata.models import ImageMetadata
import logging
import os
import pandas as pd
from pathlib import Path
import json
from fits.workflows.artifacts.provenance import PARQUET_PROVENANCE_KEY


logger = logging.getLogger(__name__)


def save_parquet(dataframe: pd.DataFrame, output_path: Path, metadata: ImageMetadata | None = None) -> Path:
    """
    Atomically save a DataFrame as a Parquet artifact.
    """
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    try:
        if metadata is None:
            dataframe.to_parquet(temporary_path, index=False)
        else:
            import pyarrow as pa
            import pyarrow.parquet as pq
            table = pa.Table.from_pandas(dataframe, preserve_index=False)
            schema_metadata = dict(table.schema.metadata or {})
            schema_metadata[PARQUET_PROVENANCE_KEY] = json.dumps(metadata.dump()).encode()
            pq.write_table(table.replace_schema_metadata(schema_metadata), temporary_path)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        logger.error("Failed to save Parquet artifact to %s", output_path)
        raise
    return output_path
