from __future__ import annotations

import logging

from stackalign import RegisterModel

from fits.workflows.experiments import ExperimentState
from fits.settings.models import RegisterChannelSettings
from fits.tasks.common.artifact_results import save_step_result
from fits.tasks.common.preparation import load_input_reader, resolve_step_run
from fits.workflows.definitions.models import StepProfile
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.tasks.registration.tuned import load_tuning, reusable_model
from fits.workflows.runtime.errors import StepExecutionError


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
    try:
        reader = load_input_reader(exp_state, step_profile)
        run = resolve_step_run(exp_state, step_profile, settings.overwrite)
        if run.is_complete:
            return [exp_state]

        source = exp_state.artifact(step_profile.input_artifact)
        tuned = load_tuning(source, "channel") if source is not None else None
        if tuned is not None:
            settings = settings.model_copy(update=tuned.settings.to_payload_dict())
        
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
           
        register = reusable_model(tuned, array=input_array, axes=input_axes,
                                  labels=tuple(reader.channel_labels or ()), settings=settings,
                                  reference_channel=ref_channel)
        if register is None:
            register = RegisterModel(backend=plan.backend)
            excluded = ([reader.resolve_channel_positions(label)[0] for label in settings.exclude_channel]
                        if settings.exclude_channel else None)
            register.fit_channel(array=input_array,
                                 axes=input_axes,
                                 method=plan.method,
                                 reference_channel=ref_channel,
                                 reference_frame=settings.reference_frame,
                                 exclude_channels=excluded)
        
        registered_array = register.apply(array=input_array, axes=input_axes)
        
        params = settings.to_payload_dict()
        params.update({'backend': plan.backend, 'method': plan.method})
        updated_state = exp_state.with_metadata(step_name=step_profile.step_name,
                                                created_by=step_profile.distribution,
                                                exported_channel='all',
                                                channels_params=params)
        
        new_state = save_step_result(reader=reader,
                                    array=registered_array,
                                    export_channels=reader.channel_labels,
                                    updated_state=updated_state,
                                    step_profile=step_profile,)
        return [new_state]        

    except Exception as e:
        logger.exception("%s failed for %s", step_profile.step_name, exp_state.experiment_id)
        raise StepExecutionError(f"Step {str(step_profile.step_name)!r} failed for "
                                f"{exp_state.experiment_id}: {e}") from e
    
