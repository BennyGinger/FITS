from __future__ import annotations

import logging

from stackalign import RegisterModel

from fits.workflows.experiments import ExperimentState
from fits.settings.models import RegisterTimeSettings
from fits.tasks.common.artifact_results import save_step_result
from fits.tasks.common.preparation import load_input_reader, resolve_step_run
from fits.workflows.definitions.models import StepProfile
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.workflows.runtime.errors import StepExecutionError


logger = logging.getLogger(__name__)


def register_time(settings: RegisterTimeSettings,
                  exp_state: ExperimentState, 
                  step_profile: StepProfile
                  ) -> list[ExperimentState]:
    """
    Process a single experiment through the time-wise registration step.
    
    Args:
        settings: RegisterTime step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata 
    
    Returns:
        List of one output experiment state. Time-wise registration produces a single output artifact.
    """
    try:
        reader = load_input_reader(exp_state, step_profile)
        run = resolve_step_run(exp_state, step_profile, settings.overwrite)
        if run.is_complete:
            return [exp_state]

        plan = resolve_registration_plan(settings.context, 
                                         backend=settings.backend, 
                                         method=settings.method)
        if plan.mode != "time":
            raise ValueError(f"Registration context {settings.context!r} resolves to "
                            f"{plan.mode!r}, not time-wise registration.")

        input_result = reader.get_array()
        input_array = input_result.array
        input_axes = input_result.axes
        
        fit_channel: int | None = None
        if 'C' in input_axes:
            if settings.fit_channel is None:
                fit_channel = 0  # default to first channel if not specified
                logger.warning("No fit_channel specified for TCYX data. Defaulting to channel 0.")
            else:
                fit_channel = reader.resolve_channel_positions(settings.fit_channel)[0]
        
        logger.debug("%s will be executed | context=%s backend=%s method=%s "
                     "reference_strategy=%s fit_channel=%s input_shape=%s input_axes=%s",
                     step_profile.step_name,
                     settings.context,
                     plan.backend,
                     plan.method,
                     settings.reference_strategy,
                     fit_channel,
                     input_array.shape,
                     input_axes,)

        register = RegisterModel(backend=plan.backend)
        register.fit_time(array=input_array, 
                          axes=input_axes, 
                          method=plan.method, 
                          reference_strategy=settings.reference_strategy, 
                          fit_channel=fit_channel)
        
        registered_array = register.apply(array=input_array, 
                                          axes=input_axes)
        
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
