from __future__ import annotations
import logging
from bioimagequant import CompartmentSettings
from fisch.workflows.experiments import ExperimentState
from fisch.settings.models import ExtractSettings
from fisch.tasks.analysis.extraction.manager import ExtractionManager
from fisch.tasks.analysis.extraction.compartment_export import export_compartments
from fisch.tasks.analysis.identity import add_quantification_ids
from fisch.tasks.analysis.tracking_summary import add_track_statistics
from fisch.tasks.analysis.tracking_motion import add_track_motion
from fisch.tasks.common.artifact_results import complete_step_result
from fisch.tasks.common.preparation import resolve_step_run
from fisch.tasks.common.table_results import save_parquet
from fisch.workflows.definitions.models import StepProfile
from fisch.workflows.runtime.errors import StepExecutionError
from fisch.workflows.artifacts.provenance import revision_payload


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
        compartments = None
        if settings.compartments:
            compartments = CompartmentSettings(membrane_thickness=settings.membrane_thickness,
                                               dilation_radius=settings.dilation_radius,
                                               )
        run = resolve_step_run(exp_state, step_profile, settings.overwrite)
        if run.is_complete:
            if compartments is not None and settings.save_compartment_masks:
                export_compartments(exp_state, compartments)
            return [exp_state]

        # Drawing flags/counts configure collection, not numerical extraction.
        # Reuse every discovered reference, including when drawing is disabled.
        manager = ExtractionManager(exp_state, profile=step_profile)
        extractor = manager.prepare_quantification()

        dataframe = extractor.quantify(additional_properties=settings.additional_properties,
                                       workers=settings.frame_workers,
                                       compartments=compartments,
                                       )

        # Add FIScH-specific provenance to the extracted measurements.
        dataframe = add_quantification_ids(dataframe, exp_state.portable_experiment_id)
        add_track_statistics(dataframe)
        add_track_motion(dataframe, pixel_size=extractor.pixel_size)

        # Save the quantification DataFrame to a Parquet file in the experiment's workdir
        output_path = (exp_state.workdir / step_profile.output_name)

        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                exported_channel="all",
                                                channels_params=settings.model_dump(),
                                                )
        payload = revision_payload(manager.image_reader, updated_state, step_profile, export_channels="all")
        save_path = save_parquet(dataframe, output_path, payload)
        if compartments is not None and settings.save_compartment_masks:
            export_compartments(exp_state, compartments, profile=step_profile)

        new_state = complete_step_result(updated_state, step_profile, save_path)
        return [new_state]

    except Exception as exc:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for "
                                f"{exp_state.experiment_id}: {exc}") from exc
