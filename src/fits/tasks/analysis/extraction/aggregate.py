from collections.abc import Mapping, Sequence
from pathlib import Path
import logging
from typing import Any

from fits.environment.constant import StepName, ARTI_QUANTI
from fits.environment.state import ExperimentState
from fits.tasks.analysis.aggregate import save_master_analysis_table


logger = logging.getLogger(__name__)


def aggregate_quantification(effective_cfg: Mapping[str, Any], final_states: Sequence[ExperimentState], run_dir: Path,) -> None:
    extract_cfg = effective_cfg.get(StepName.EXTRACT)

    if isinstance(extract_cfg, Mapping) and extract_cfg.get("enabled", False):
        master_path = _save_master_quantification(final_states, run_dir)

        if master_path is None:
            logger.warning("No quantification artifacts were produced; ""master Parquet was not created.")
        else:
            logger.info("Master quantification saved to %s", master_path)
            
            
def _save_master_quantification(states: Sequence[ExperimentState], run_dir: Path,) -> Path | None:
    """
    Save a master quantification Parquet file by aggregating all individual quantification artifacts from the provided experiment states.

    Args:
        states: List of ExperimentState instances to aggregate.
        run_dir: Directory where the master Parquet file will be saved.
    
    Returns:
        Path to the saved master Parquet file, or None if no quantification artifacts were found.
    """
    return save_master_analysis_table(
        states,
        run_dir,
        artifact_kind=ARTI_QUANTI,
        output_name="master_quantification.parquet",)
