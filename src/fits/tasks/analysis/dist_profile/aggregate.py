from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
from pathlib import Path
from typing import Any

from fits.environment.constant import ARTI_DIST_PROF, StepName
from fits.environment.state import ExperimentState
from fits.tasks.analysis.aggregate import save_master_analysis_table


logger = logging.getLogger(__name__)


def aggregate_distance_profiles(effective_cfg: Mapping[str, Any],
                                final_states: Sequence[ExperimentState],
                                run_dir: Path,
                                ) -> None:
    """Create the master distance-profile table when the step is enabled."""
    config = effective_cfg.get(StepName.DISTANCE_PROFILE)
    if not isinstance(config, Mapping) or not config.get("enabled", False):
        return

    master_path = save_master_analysis_table(
        final_states,
        run_dir,
        artifact_kind=ARTI_DIST_PROF,
        output_name="master_distance_profile.parquet",)
    if master_path is None:
        logger.warning(
            "No distance-profile artifacts were produced; master Parquet was not created.")
    else:
        logger.info("Master distance profile saved to %s", master_path)
