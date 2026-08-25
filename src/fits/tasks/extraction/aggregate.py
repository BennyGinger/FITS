from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import logging

import pandas as pd

from fits.environment.constant import StepName, ARTI_QUANTI
from fits.environment.state import ExperimentState


logger = logging.getLogger(__name__)


def aggregate_quantification(effective_cfg: Mapping, final_states: Sequence[ExperimentState], run_dir: Path,) -> None:
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
    quant_paths: list[Path] = []
    for state in states:
        quant_path = state.artifact(ARTI_QUANTI)
        if quant_path is not None and quant_path.exists():
            quant_paths.append(quant_path)

    if not quant_paths:
        return None

    
    # Read and concatenate all Parquet files into a single DataFrame
    dataframes = [pd.read_parquet(path) for path in quant_paths]
    master_df = pd.concat(dataframes, ignore_index=True)

    # Save the master DataFrame to a Parquet file
    master_path = run_dir / "master_quantification.parquet"
    temporary_path = master_path.with_suffix(f"{master_path.suffix}.tmp")
    
    try:
        master_df.to_parquet(temporary_path, index=False)
        os.replace(temporary_path, master_path)
    
    except Exception as e:
        temporary_path.unlink(missing_ok=True)
        logger.error("Failed to save master quantification: %s", e)
        raise

    return master_path