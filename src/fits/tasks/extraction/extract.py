import logging
import os
from pathlib import Path

import pandas as pd

from fits.environment.state import ExperimentState
from fits.settings.models import ExtractSettings
from fits.tasks.extraction.manager import ExtractionManager
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import decide_run


logger = logging.getLogger(__name__)


def extract(settings: ExtractSettings, exp_state: ExperimentState, step_profile: StepProfile,) -> list[ExperimentState]:
    """
    Process a single experiment through the extract step.
    
    Args:
        settings: Extract step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
    
    Returns:
        List of one output experiment state. Extract step produces a single output artifact.
    """
    try:
        run = decide_run(
            exp_state,
            step_profile,
            settings.overwrite,
        )

        if run.is_complete:
            return [exp_state]

        manager = ExtractionManager(exp_state)
        extractor = manager.prepare_quantification()

        dataframe = extractor.quantify(
            additional_properties=settings.additional_properties,
            workers=settings.frame_workers,
        )
        # Add FITS-specific provenance to the extracted measurements.
        dataframe.insert(0, "experiment_id", exp_state.experiment_id)

        # Save the quantification DataFrame to a Parquet file in the experiment's workdir
        output_path = (exp_state.workdir / step_profile.output_name)

        save_path = _save_quantification(
            dataframe,
            output_path,)

        updated_state = exp_state.with_metadata(
            step_name=step_profile.step_name,
            created_by=step_profile.distribution,)

        new_state = updated_state.with_complete_step(
            step_name=step_profile.step_name,
            artifact_kind=step_profile.output_artifact,
            artifact_path=save_path,)

        new_state.save_state()
        return [new_state]

    except Exception as exc:
        logger.exception(
            "%s failed for %s",
            step_profile.step_name,
            exp_state.experiment_id,
        )
        print(
            f"[ERROR] Step {step_profile.step_name!r} failed for "
            f"{exp_state.experiment_id}: {exc}"
        )
        return []

 
def _save_quantification(dataframe: pd.DataFrame, output_path: Path,) -> Path:
    """
    Atomically save the quantification DataFrame to a Parquet file.
    """
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")

    try:
        dataframe.to_parquet(temporary_path, index=False,)
        os.replace(temporary_path, output_path)
    
    except Exception:
        temporary_path.unlink(missing_ok=True)
        logger.error("Failed to save quantification to %s", output_path)
        raise

    return output_path
