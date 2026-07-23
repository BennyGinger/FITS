# from __future__ import annotations

# import logging
# from typing import Any

# from fits_io.client import FitsIO
# from stackalign import RegisterModel

# import fits.environment.constant as cst
# from fits.environment.constant import StepName, FitsName
# from fits.environment.state import ExperimentState
# from fits.settings.models import RegisterChannelSettings
# from fits.workflows.arrays.channel_merge import included_channel_indices, merge_channel_subset_back, resolve_excluded_channel_indices, take_channels
# from fits.workflows.arrays.loading import get_array
# from fits.workflows.arrays.validations import resolve_channel_index
# from fits.tasks.registration.registration_resolver import resolve_registration_plan
# from fits.workflows.engines.run_decision import decide_run
# from fits.workflows.metadata.builder import build_step_project_metadata
# from fits.workflows.metadata.loading import load_project_metadata_from_reader
# from fits.workflows.engines.models import StepProfile


# logger = logging.getLogger(__name__)


# def register_channel_one(settings: RegisterChannelSettings, exp_state: ExperimentState, step_profile: StepProfile) -> list[ExperimentState]:
#     """
#     """
#     input_path = exp_state.artifact(step_profile.input_artifact)
#     if input_path is None:
#         logger.error("%s failed for loading %s: missing input",
#                      step_profile.step_name,
#                      step_profile.input_artifact)
#         return []

#     try:
#         reader = FitsIO.from_path(input_path)
        
#         run = decide_run(exp_state, step_profile, settings.overwrite)
#         if run.is_complete:
#             logger.debug("Skipping %s for %s: already completed.", 
#                          step_profile.step_name, 
#                          exp_state.original_image)
#             return [exp_state]

#         input_array = reader.get_array()
#         input_axis_order 
        
        
#         plan = resolve_registration_plan(settings.context, backend=settings.backend, method=settings.method)
#         if plan.mode != "channel":
#             raise ValueError(f"Context '{settings.context}' is not a channel-wise registration preset.")
#         if 'C' not in input_axis_order:
#             raise ValueError("Channel-wise registration requires a C axis in the input array.")

#         c_idx = input_axis_order.index('C')
#         fit_array = input_array
#         included_indices = list(range(input_array.shape[c_idx]))
#         if settings.exclude_channel:
#             excluded_indices = resolve_excluded_channel_indices(settings.exclude_channel, reader.channel_labels, field_name="exclude_channel")
#             included_indices = included_channel_indices(input_array.shape[c_idx], excluded_indices)
#             if not included_indices:
#                 raise ValueError("Channel-wise registration cannot run because exclude_channel removes all channels.")
#             fit_array = take_channels(input_array, input_axis_order, included_indices)

#         if reader.channel_labels is None:
#             included_channel_labels = None
#         else:
#             included_channel_labels = [reader.channel_labels[i] for i in included_indices]

#         resolved_reference_channel = resolve_channel_index(settings.reference_channel, included_channel_labels, "reference_channel")
#         if resolved_reference_channel is None:
#             raise ValueError(f"Context '{settings.context}' requires a reference_channel but none was provided. Set 'reference_channel' to a channel label or local channel index.")

#         register = RegisterModel(backend=plan.backend)
#         register.fit_channel(array=fit_array, 
#                              axes=input_axis_order, 
#                              method=plan.method, 
#                              reference_channel=resolved_reference_channel, 
#                              reference_frame=settings.reference_frame)
#         transformed_included = register.apply(array=fit_array, axes=input_axis_order)
        
#         if len(included_indices) == input_array.shape[c_idx]:
#             registered_array = transformed_included
#         else:
#             registered_array = merge_channel_subset_back(input_array, transformed_included, input_axis_order, included_indices)

#         existing_project_metadata = load_project_metadata_from_reader(reader)
#         step_metadata: dict[str, Any] = {
#             "context": settings.context,
#             "mode": plan.mode,
#             "backend": plan.backend,
#             "method": plan.method,
#             "reference_channel": settings.reference_channel,
#             "resolved_reference_channel": resolved_reference_channel,
#             "reference_frame": settings.reference_frame,
#             "exclude_channel": settings.exclude_channel,
#             "included_channel_indices": included_indices,
#             "included_channel_labels": included_channel_labels,}
        
#         project_metadata = build_step_project_metadata(existing_project_metadata=existing_project_metadata, step_profile=step_profile, user_name=ctx.user_name, step_metadata=step_metadata, channel_metadata=None)

#         reader.save_array(registered_array, axis_order=input_axis_order, channel_labels=reader.channel_labels, output_name=output_name, custom_metadata=project_metadata)
#         logger.debug("%s completed for %s", step_profile.step_name, exp_state.workdir_relative(run_dir))

#         new_st = exp_state.with_completed_step(StepName.REGISTER_CHANNEL)
#         logger.debug("Produced new ExperimentState: %s", new_st)
#         new_st.save()
#         return new_st
#     except Exception as e:
#         logger.exception("%s failed for %s", step_profile.step_name, exp_state.workdir)
#         print(f"[ERROR] Step '{step_profile.step_name}' failed for {exp_state.workdir}: {e}")
#         return exp_state.with_error(StepName.REGISTER_CHANNEL, str(e))
