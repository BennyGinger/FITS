# from __future__ import annotations

# from collections.abc import Mapping
# from typing import Any

# from fits.workflows.engines.models import StepProfile, build_provenance_stamp
# from fits.workflows.metadata.merge import merge_step_metadata


# def build_step_project_metadata(existing_project_metadata: Mapping[str, Any] | None, *, step_profile: StepProfile, user_name: str, step_metadata: Mapping[str, Any] | None = None, channel_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
#     """
#     Build/update pipeline-owned project metadata for a workflow step.
    
#     Args:
#         existing_project_metadata: Current project metadata dict to update, or None to create new.
#         step_profile: Metadata about the current workflow step for provenance tracking.
#         user_name: Name of the user executing the step for provenance tracking.
#         step_metadata: Optional dict of step-specific metadata to include in the step's provenance.
#         channel_metadata: Optional dict of per-channel metadata to include in the step's provenance under a "channels" key. Should be a dict mapping channel names to metadata dicts.
#     """
#     out = dict(existing_project_metadata) if isinstance(existing_project_metadata, Mapping) else {}

#     pipeline_block_raw = out.get("pipeline")
#     pipeline_block = dict(pipeline_block_raw) if isinstance(pipeline_block_raw, Mapping) else {}
#     pipeline_block.update({'user_name': user_name,
#                            **build_provenance_stamp('fits')})
#     out["pipeline"] = pipeline_block

#     steps_block_raw = out.get("steps")
#     steps_block = dict(steps_block_raw) if isinstance(steps_block_raw, Mapping) else {}

#     step_name = step_profile.step_name
#     existing_step = steps_block.get(step_name)
#     updated_step = merge_step_metadata(existing_step, build_provenance_stamp(step_profile.distribution))

#     if step_metadata:
#         updated_step = merge_step_metadata(updated_step, step_metadata)

#     if channel_metadata:
#         updated_step = merge_step_metadata(updated_step, {"channels": channel_metadata})

#     steps_block[step_name] = updated_step
#     out["steps"] = steps_block
#     return out
