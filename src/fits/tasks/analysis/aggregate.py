from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import logging
import os
import json
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from fits.environment.constant import ARTI_QUANTI, ArtifactType
from fits.tasks.analysis.identity import add_quantification_ids, add_condition_tags
from fits.tasks.analysis.tracking_summary import add_track_statistics
from fits.workflows.experiments import ExperimentState, active_states
from fits.workflows.checks.analysis import MEMBERSHIP_KEY, analysis_membership
from fits.environment.paths import EXPERIMENT_DIR_NAME


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
    states = [replace(state, run_dir=run_dir) for state in active_states(states)]
    master_path = run_dir / output_name
    tables: list[tuple[Path, tuple[str, ...], str]] = []
    for state in states:
        table_path = state.artifact(artifact_kind)
        if table_path is not None and table_path.exists():
            experiment_id = replace(state, run_dir=run_dir).analysis_experiment_id
            tables.append((table_path, _condition_values(state, run_dir), experiment_id))

    if not tables:
        master_path.unlink(missing_ok=True)
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
        padded: tuple[str | None, ...] = (*conditions, *([None] * (condition_depth - len(conditions))))
        add_condition_tags(dataframe, padded)
        dataframes.append(dataframe)

    temporary_path = master_path.with_suffix(f"{master_path.suffix}.tmp")
    try:
        table = pa.Table.from_pandas(pd.concat(dataframes, ignore_index=True), preserve_index=False)
        metadata = {**(table.schema.metadata or {}),
                    MEMBERSHIP_KEY: json.dumps(analysis_membership(states, artifact_kind)).encode('utf-8')}
        pq.write_table(table.replace_schema_metadata(metadata), temporary_path)
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
        parent = state.original_image.parent
        if parent != run_dir and (parent / EXPERIMENT_DIR_NAME).is_dir():
            parent = parent.parent
        relative_parent = parent.relative_to(run_dir)
    except ValueError as exc:
        raise ValueError(f"Original image {state.original_image} is outside run directory {run_dir}.") from exc
    return relative_parent.parts
