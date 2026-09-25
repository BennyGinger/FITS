import logging

from fits.workflows.experiments import ExperimentState
from fits.settings.models import ExtractSettings
from fits.tasks.analysis.extraction.manager import ExtractionManager
from fits.tasks.common.artifact_results import complete_step_result
from fits.tasks.common.preparation import resolve_step_run
from fits.tasks.common.table_results import save_parquet
from fits.workflows.definitions.models import StepProfile
from fits.workflows.runtime.errors import StepExecutionError


logger = logging.getLogger(__name__)


def extract(settings: ExtractSettings, 
            exp_state: ExperimentState, 
            step_profile: StepProfile,
            ) -> list[ExperimentState]:
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
        run = resolve_step_run(exp_state,
                            step_profile,
                            settings.overwrite,)
        if run.is_complete:
            return [exp_state]

        # Drawing flags/counts configure collection, not numerical extraction.
        # Reuse every discovered reference, including when drawing is disabled.
        manager = ExtractionManager(exp_state)
        extractor = manager.prepare_quantification()

        dataframe = extractor.quantify(additional_properties=settings.additional_properties,
                                    workers=settings.frame_workers,)

        # Add FITS-specific provenance to the extracted measurements.
        dataframe.insert(0, "experiment_id", exp_state.experiment_id)

        # Save the quantification DataFrame to a Parquet file in the experiment's workdir
        output_path = (exp_state.workdir / step_profile.output_name)

        save_path = save_parquet(dataframe, output_path,)

        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,)

        new_state = complete_step_result(updated_state,
                                        step_profile,
                                        save_path,)
        return [new_state]

    except Exception as exc:
        logger.exception("%s failed for %s",
                        step_profile.step_name,
                        exp_state.experiment_id,)
        raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for "
                                f"{exp_state.experiment_id}: {exc}") from exc
