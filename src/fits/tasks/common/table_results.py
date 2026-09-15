import logging
import os
from pathlib import Path

import pandas as pd


logger = logging.getLogger(__name__)


def save_parquet(dataframe: pd.DataFrame, output_path: Path) -> Path:
    """
    Atomically save a DataFrame as a Parquet artifact.
    """
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    try:
        dataframe.to_parquet(temporary_path, index=False)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        logger.error("Failed to save Parquet artifact to %s", output_path)
        raise
    return output_path
