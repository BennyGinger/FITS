from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from fits_io import FitsIO
from fits.workflows.experiments import ExperimentState, save_experiment_state, load_experiment_state
from fits.environment.constant import ARTI_RAW, StepName
from fits.workflows.definitions.models import StepProfile
from fits.workflows.runtime.run_decision import decide_run
from fits.workflows.runtime.errors import StepExecutionError
from fits.workflows.checks.space import require_processing_space
from fits.settings.models import ConvertSettings
from fits.workflows.artifacts.provenance import produced_metadata
from fits_io.metadata.provenance import input_reference
from fits.workflows.experiments.acquisitions import group_acquisition
from fits.environment.paths import experiment_state_path


logger = logging.getLogger(__name__)
STEP_CONVERT = StepName.CONVERT


def convert(settings: ConvertSettings,
            exp_state: ExperimentState,
            step_profile: StepProfile,
            ) -> list[ExperimentState]:
    """
    Process a single experiment through the convert step.

    Args:
        settings: Convert step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
        output_name: Output FITS name scheme
        
    Returns:
        List of output experiment states. Single-series returns one state,
        multi-series returns multiple states (one per series).
    """
    run = decide_run(exp_state, step_profile, settings.overwrite)

    if run.is_complete:
        logger.debug("Skipping %s for %s as it is up to date.",
                     step_profile.step_name,
                     exp_state.original_image,
                     )
        return [exp_state]

    require_processing_space(exp_state.run_dir or exp_state.workdir, ((exp_state, 1),))
    # Run the conversion step
    logger.debug("%s will be executed with settings: %s", step_profile.step_name, settings.model_dump())
    try:
        grouped = group_acquisition(exp_state.original_image, exp_state.acquisition_directory)
        exp_state = replace(exp_state, artifacts={**exp_state.artifacts,
            ARTI_RAW: Path(os.path.relpath(grouped, exp_state.workdir))})
        source = FitsIO.from_path(grouped)

        color_options = ({"channel_colors": settings.source_channel_colors}
                         if settings.source_channel_colors is not None else {})
        selection = source.resolve_channel_selection(channel_labels=settings.channel_labels or None,
                                                     export_channels=settings.export_channels,
                                                     **color_options,
                                                     )

        series_readers = source.split_series()

        pending_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                exported_channel="all",
                                                channels_params=settings.model_dump(),
                                                )

        out_states: list[ExperimentState] = []
        for series_index, reader in enumerate(series_readers, start=1):
            output_path = grouped.parent / f"{grouped.stem}_s{series_index}" / step_profile.output_name
            branch_base = pending_state
            if exp_state.execution_scope is not None:
                old = None
                if experiment_state_path(output_path.parent).is_file():
                    old = replace(load_experiment_state(output_path.parent, run_dir=exp_state.run_dir),
                                  execution_scope=exp_state.execution_scope,
                                  )
                if str(step_profile.step_name) not in exp_state.execution_scope.get(output_path.parent, ()):
                    if old is not None and output_path.parent in exp_state.execution_scope:
                        out_states.append(old)
                    continue
                if old is not None:
                    branch_base = old.with_metadata(step_name=step_profile.step_name,
                                                    created_by=step_profile.distribution,
                                                    exported_channel="all",
                                                    channels_params=settings.model_dump(),
                                                    )
            conversion_meta = pending_state.metadata_dump
            conversion_meta['steps'] = {step_profile.step_name: conversion_meta['steps'][step_profile.step_name]}
            output = reader.prepare_conversion(selection=selection,
                                               output_name=step_profile.output_name,
                                               artifact_kind=step_profile.output_artifact,
                                               created_by=step_profile.distribution,
                                               custom_metadata=produced_metadata(conversion_meta),
                                               z_projection=settings.z_projection,
                                               )

            output_path.parent.mkdir(parents=True, exist_ok=True)
            path = reader.save_array(array=output.array,
                                     metadata=output.metadata.new_revision([
                                         input_reference(exp_state.original_image,
                                                         reader.reader.metadata,
                                                         output_path.parent,
                                                         )]),
                                     output_path=output_path,
                                     compression=settings.compression,)

            branch_state = branch_base.with_complete_step(step_name=step_profile.step_name,
                                                          artifact_kind=step_profile.output_artifact,
                                                          artifact_path=path,
                                                          workdir=path.parent,
                                                          )
            save_experiment_state(branch_state)
            out_states.append(branch_state)

            logger.debug("Produced converted branch %s from %s.",
                         branch_state.experiment_id,
                         exp_state.original_image,
                         )

        logger.debug("%s completed for %s with %d output series.",
                     step_profile.step_name,
                     exp_state.original_image,
                     len(out_states),
                     )
        return out_states
    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.original_image)
        raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for "
                                f"{exp_state.original_image}: {e}") from e
