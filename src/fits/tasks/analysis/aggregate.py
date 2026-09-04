from __future__ import annotations

from collections.abc import Sequence
import logging
import os
from pathlib import Path

import pandas as pd

from fits.environment.constant import ArtifactType
from fits.environment.state import ExperimentState


logger = logging.getLogger(__name__)


def save_master_analysis_table(states: Sequence[ExperimentState],
                               run_dir: Path,
                               *,
                               artifact_kind: ArtifactType,
                               output_name: str,
                               ) -> Path | None:
    """Aggregate analysis Parquets and retain folder-based condition tags."""
    tables: list[tuple[Path, tuple[str, ...]]] = []
    for state in states:
        table_path = state.artifact(artifact_kind)
        if table_path is not None and table_path.exists():
            tables.append((table_path, _condition_values(state, run_dir)))

    if not tables:
        return None

    condition_depth = max(len(conditions) for _, conditions in tables)
    dataframes: list[pd.DataFrame] = []
    for table_path, conditions in tables:
        dataframe = pd.read_parquet(table_path)
        insert_at = 1 if "experiment_id" in dataframe.columns else 0
        for level in range(condition_depth):
            value = conditions[level] if level < len(conditions) else None
            dataframe.insert(
                insert_at + level,
                f"condition_level_{level + 1}",
                pd.Series(value, index=dataframe.index, dtype="string"),)
        dataframes.append(dataframe)

    master_path = run_dir / output_name
    temporary_path = master_path.with_suffix(f"{master_path.suffix}.tmp")
    try:
        pd.concat(dataframes, ignore_index=True).to_parquet(
            temporary_path, index=False)
        os.replace(temporary_path, master_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        logger.exception("Failed to save master analysis table %s.", master_path)
        raise
    return master_path


def _condition_values(state: ExperimentState, run_dir: Path) -> tuple[str, ...]:
    """Return user-created folders between the run directory and source image."""
    try:
        relative_parent = state.original_image.parent.relative_to(run_dir)
    except ValueError as exc:
        raise ValueError(
            f"Original image {state.original_image} is outside run directory {run_dir}.") from exc
    return relative_parent.parts
