from __future__ import annotations

import logging

from fits_io.client import FitsIO
from stackalign import RegisterModel

from fits.environment.state import ExperimentState
from fits.settings.models import RegisterChannelSettings
from fits.workflows.engines.run_decision import decide_run
from fits.workflows.engines.models import StepProfile
from fits.tasks.registration.registration_resolver import resolve_registration_plan


logger = logging.getLogger(__name__)


def register_channel(settings: RegisterChannelSettings,
                     exp_state: ExperimentState, 
                     step_profile: StepProfile
                     ) -> list[ExperimentState]:
    """
    Prcess a single experiment through the channel-wise registration step.
    
    Args:
        settings: RegisterChannel step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
        
    Returns:
        List of one output experiment state. Channel-wise registration produces a single output artifact.
    """
    input_path = exp_state.artifact(step_profile.input_artifact)
    if input_path is None:
        logger.error("%s failed for loading %s: missing input",
                     step_profile.step_name,
                     step_profile.input_artifact)
        return []

    try:
        reader = FitsIO.from_path(input_path)
        run = decide_run(exp_state, step_profile, settings.overwrite)
        if run.is_complete:
            logger.debug("Skipping %s for %s: already completed.",
                         step_profile.step_name,
                         exp_state.experiment_id)
            return [exp_state]
        
        plan = resolve_registration_plan(settings.context,
                                         backend=settings.backend,
                                         method=settings.method)
        if plan.mode != "channel":
            raise ValueError(f"Registration context {settings.context!r} resolves to "
                            f"{plan.mode!r}, not channel-wise registration.")

        input_result = reader.get_array()
        input_array = input_result.array
        input_axes = input_result.axes        
    
        ref_channel: int | None = None
        if settings.reference_channel is not None:
            ref_channel = reader.resolve_channel_positions(settings.reference_channel)[0]
        
        logger.debug("%s will be executed | context=%s backend=%s method=%s "
                     "reference_channel=%s reference_frame=%s input_shape=%s input_axes=%s",
                     step_profile.step_name,
                     settings.context,
                     plan.backend,
                     plan.method,
                     ref_channel,
                     settings.reference_frame,
                     input_array.shape,
                     input_axes,)
           
        register = RegisterModel(backend=plan.backend)
        register.fit_channel(array=input_array,
                             axes=input_axes,
                             method=plan.method,
                             reference_channel=ref_channel,
                             reference_frame=settings.reference_frame)
        
        registered_array = register.apply(array=input_array, axes=input_axes)
        
        params = settings.to_payload_dict()
        params.update({'backend': plan.backend, 'method': plan.method})
        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                exported_channel='all',
                                                channels_params=params)
        
        save_path = reader.save_array(registered_array,
                                      output_name=step_profile.output_name,
                                      export_channels=reader.channel_labels,
                                      artifact_kind=step_profile.output_artifact,
                                      created_by=step_profile.distribution,
                                      custom_metadata=updated_state.metadata_dump)
        
        new_state = updated_state.with_complete_step(step_name=step_profile.step_name,
                                                     artifact_kind=step_profile.output_artifact,
                                                     artifact_path=save_path)
        logger.debug("%s completed for %s",
                     step_profile.step_name,
                     exp_state.experiment_id,)
        logger.debug("Produced new ExperimentState: %s", new_state)
        new_state.save_state()
        return [new_state]        

    except Exception as e:
            logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
            print(f"[ERROR] Step '{step_profile.step_name}' failed for {exp_state.experiment_id}: {e}")
            return []  
    
