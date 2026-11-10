"""Assembly of saved and newly discovered experiment states."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fisch.environment.constant import StepName
from fisch.workflows.experiments.model import ExperimentState
from fisch.workflows.experiments.persistence import discover_saved_states
from fisch.workflows.experiments.exclusion import active_raw_files
from fisch.workflows.metadata import PipelineMetadata


def assemble_experiment_states(run_dir: Path,
                                raw_files: Sequence[Path],
                                workflow_cfg: Mapping[str, Any],
                                user_name: str,
                                ) -> list[ExperimentState]:
    """
    Combine reusable saved states with states for previously unseen raw inputs.
    """
    saved_states = discover_saved_states(run_dir)
    raw_states = [ExperimentState.init(raw_file.parent,
                                        raw_file,
                                        run_dir=run_dir,
                                        proc_meta=PipelineMetadata.init(user_name=user_name),)
                    for raw_file in active_raw_files(raw_files, saved_states)]
    
    if _convert_overwrites(workflow_cfg):
        return raw_states
    
    converted_originals = {state.original_image for state in saved_states}
    remaining_raw_states = [state for state in raw_states
                            if state.original_image not in converted_originals]
    return saved_states + remaining_raw_states


def _convert_overwrites(workflow_cfg: Mapping[str, Any]) -> bool:
    """
    Return whether enabled conversion is configured to overwrite outputs.
    """
    step_cfg = workflow_cfg.get(StepName.CONVERT)
    if not isinstance(step_cfg, Mapping) or not step_cfg.get("enabled", False):
        return False
    
    params = step_cfg.get("params")
    return isinstance(params, Mapping) and bool(params.get("overwrite", False))
