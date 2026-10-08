from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import logging
import os
from pathlib import Path

import pandas as pd

from fits.environment.constant import ARTI_QUANTI, ArtifactType
from fits.tasks.analysis.identity import add_quantification_ids
from fits.tasks.analysis.tracking_summary import add_track_statistics
from fits.workflows.experiments import ExperimentState


logger = logging.getLogger(__name__)


def save_master_analysis_table(states: Sequence[ExperimentState],
                               run_dir: Path,
                               *,
                               artifact_kind: ArtifactType,
                               output_name: str,
                               ) -> Path | None:
    """
    Aggregate analysis Parquets and retain folder-based condition tags.
    """
    tables: list[tuple[Path, tuple[str, ...], str]] = []
    for state in states:
        table_path = state.artifact(artifact_kind)
        if table_path is not None and table_path.exists():
            experiment_id = replace(state, run_dir=run_dir).analysis_experiment_id
            tables.append((table_path, _condition_values(state, run_dir), experiment_id))

    if not tables:
        return None

    condition_depth = max(len(conditions) for _, conditions, _ in tables)
    dataframes: list[pd.DataFrame] = []
    for table_path, conditions, experiment_id in tables:
        dataframe = pd.read_parquet(table_path)
        # Reused outputs may predate portable IDs, or the run may have moved.
        # Normalize the master without rewriting individual scientific artifacts.
        if artifact_kind == ARTI_QUANTI:
            dataframe = add_quantification_ids(dataframe, experiment_id)
            add_track_statistics(dataframe)
        elif "experiment_id" in dataframe:
            dataframe["experiment_id"] = experiment_id
        else:
            dataframe.insert(0, "experiment_id", experiment_id)
        insert_at = 1 if "experiment_id" in dataframe.columns else 0
        for level in range(condition_depth):
            value = conditions[level] if level < len(conditions) else None
            dataframe.insert(insert_at + level,
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
    """
    Return user-created folders between the run directory and source image.
    """
    try:
        relative_parent = state.original_image.parent.relative_to(run_dir)
    except ValueError as exc:
        raise ValueError(f"Original image {state.original_image} is outside run directory {run_dir}.") from exc
    return relative_parent.parts
