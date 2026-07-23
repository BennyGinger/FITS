# from __future__ import annotations

# import logging
# from typing import Any

# import numpy as np
# from fits_io.client import FitsIO
# from stackalign import RegisterModel

# from fits.environment.constant import FitsName, StepName
# from fits.environment.runtime import get_ctx
# from fits.environment.state import ExperimentState
# from fits.settings.models import RegisterTimeSettings
# from fits.workflows.arrays.loading import get_array
# from fits.workflows.arrays.validations import resolve_channel_index
# from fits.tasks.registration.registration_resolver import resolve_registration_plan
# from fits.workflows.engines.run_decision import decide_run
# from fits.workflows.metadata.builder import build_step_project_metadata
# from fits.workflows.metadata.loading import load_project_metadata_from_reader
# from fits.workflows.engines.models import StepProfile


# logger = logging.getLogger(__name__)


# def register_time_one(settings: RegisterTimeSettings, exp_state: ExperimentState, step_profile: StepProfile, output_name: FitsName) -> ExperimentState:
#     if exp_state.image is None:
#         failed_state = exp_state.with_error(StepName.REGISTER_TIME, f"ExperimentState for {exp_state.original_image} has no image set; cannot run {step_profile.step_name}.")
#         logger.error("%s failed for %s: missing image input", step_profile.step_name, exp_state.original_image)
#         return failed_state

#     ctx = get_ctx()
#     run_dir = ctx.run_dir

#     try:
#         reader = FitsIO.from_path(exp_state.image)
#         run = decide_run(exp_state, step_profile.step_name, settings.overwrite)
#         if run.is_complete:
#             logger.debug("Skipping %s for %s: already completed.", step_profile.step_name, exp_state.original_image)
#             return exp_state

#         input_array, input_axis_order = get_array(reader)
#         plan = resolve_registration_plan(settings.context, backend=settings.backend, method=settings.method)
#         if plan.mode != "time":
#             raise ValueError(f"Context '{settings.context}' is not a time-wise registration preset.")

#         if 'C' in input_axis_order and settings.fit_channel is None:
#             raise ValueError("Time-wise registration on multi-channel data requires fit_channel. "
#                 "Set it to the channel label or local channel index used for fitting.")

#         resolved_fit_channel = resolve_channel_index(settings.fit_channel, reader.channel_labels, "fit_channel")
#         fit_array = input_array
#         fit_axes = input_axis_order
#         if 'C' in input_axis_order:
#             c_idx = input_axis_order.index('C')
#             assert resolved_fit_channel is not None
#             fit_array = np.take(input_array, resolved_fit_channel, axis=c_idx)
#             fit_axes = input_axis_order.replace('C', '')

#         logger.debug(
#             "Register time-fit | context=%s plan=%s input_shape=%s input_axes=%s fit_channel_requested=%s fit_channel_resolved=%s fit_shape=%s fit_axes=%s reference_strategy=%s",
#             settings.context,
#             plan,
#             input_array.shape,
#             input_axis_order,
#             settings.fit_channel,
#             resolved_fit_channel,
#             fit_array.shape,
#             fit_axes,
#             settings.reference_strategy,
#         )

#         register = RegisterModel(backend=plan.backend)
#         register.fit_time(array=fit_array, axes=fit_axes, method=plan.method, reference_strategy=settings.reference_strategy, fit_channel=None)
#         try:
#             registered_array = register.apply(array=input_array, axes=input_axis_order)
#         except Exception:
#             if 'C' not in input_axis_order:
#                 raise
#             c_idx = input_axis_order.index('C')
#             apply_axes = input_axis_order.replace('C', '')
#             transformed_channels: list[np.ndarray[Any, Any]] = []
#             for ch in range(input_array.shape[c_idx]):
#                 channel_array = np.take(input_array, ch, axis=c_idx)
#                 transformed_channels.append(register.apply(array=channel_array, axes=apply_axes))
#             registered_array = np.stack(transformed_channels, axis=c_idx)

#         existing_project_metadata = load_project_metadata_from_reader(reader)
#         step_metadata: dict[str, Any] = {
#             "context": settings.context,
#             "mode": plan.mode,
#             "backend": plan.backend,
#             "method": plan.method,
#             "reference_strategy": settings.reference_strategy,
#             "fit_channel": settings.fit_channel,
#             "resolved_fit_channel": resolved_fit_channel,
#         }
#         project_metadata = build_step_project_metadata(existing_project_metadata=existing_project_metadata, step_profile=step_profile, user_name=ctx.user_name, step_metadata=step_metadata, channel_metadata=None)

#         reader.save_array(registered_array, axis_order=input_axis_order, channel_labels=reader.channel_labels, output_name=output_name, custom_metadata=project_metadata)
#         logger.debug("%s completed for %s", step_profile.step_name, exp_state.workdir_relative(run_dir))

#         new_st = exp_state.with_completed_step(StepName.REGISTER_TIME)
#         logger.debug("Produced new ExperimentState: %s", new_st)
#         new_st.save()
#         return new_st
#     except Exception as e:
#         logger.exception("%s failed for %s", step_profile.step_name, exp_state.workdir)
#         print(f"[ERROR] Step '{step_profile.step_name}' failed for {exp_state.workdir}: {e}")
#         return exp_state.with_error(StepName.REGISTER_TIME, str(e))
