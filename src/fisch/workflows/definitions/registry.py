from __future__ import annotations

from dataclasses import replace
from typing import Any
import fisch.environment.constant as cst
from fisch.environment.constant import StepName
from fisch.settings.models import BGSubSettings, ConvertSettings, RegisterChannelSettings, RegisterTimeSettings, SegmentSettings, TrackSettings, EditTrackSettings, ExtractSettings, DistanceProfileSettings
from fisch.workflows.definitions.models import StepProfile, StepSpec
from fisch.tasks import convert, segment, remove_bg, register_channel, register_time, track, extract, run_distance_profile


REGISTRY: dict[str, StepSpec[Any]] = {
    StepName.CONVERT: StepSpec(
        profile=StepProfile(step_name=StepName.CONVERT,
                            distribution=cst.DIST_IO,
                            input_artifact=cst.ARTI_RAW,
                            output_artifact=cst.ARTI_IMG_RAW,
                            output_name=cst.ARRAY_RAW,
                            ),
        settings_model=ConvertSettings,
        item_runner=convert,
        pool="cpu"
    ),
    StepName.BG_SUB: StepSpec(
        profile=StepProfile(step_name=StepName.BG_SUB,
                            distribution=cst.DIST_BG_SUB,
                            input_artifact=cst.ARTI_IMG,
                            output_artifact=cst.ARTI_IMG_BGSUB,
                            output_name=cst.ARRAY_BGSUB,
                            ),
        settings_model=BGSubSettings,
        item_runner=remove_bg,
        pool="cpu"
    ),
    StepName.REGISTER_TIME: StepSpec(
        profile=StepProfile(step_name=StepName.REGISTER_TIME,
                            distribution=cst.DIST_REGISTER,
                            input_artifact=cst.ARTI_IMG,
                            output_artifact=cst.ARTI_IMG_TIME,
                            output_name=cst.ARRAY_REG_TIME,
                            ),
        settings_model=RegisterTimeSettings,
        item_runner=register_time,
        pool="cpu",
        max_concurrency=1
    ),
    StepName.REGISTER_CHANNEL: StepSpec(
        profile=StepProfile(step_name=StepName.REGISTER_CHANNEL,
                            distribution=cst.DIST_REGISTER,
                            input_artifact=cst.ARTI_IMG,
                            output_artifact=cst.ARTI_IMG_CHANNEL,
                            output_name=cst.ARRAY_REG_CHANNEL,
                            ),
        settings_model=RegisterChannelSettings,
        item_runner=register_channel,
        pool="cpu"
    ),
    StepName.SEGMENT: StepSpec(
        profile=StepProfile(step_name=StepName.SEGMENT,
                            distribution=cst.DIST_SEG,
                            input_artifact=cst.ARTI_IMG,
                            output_artifact=cst.ARTI_SEG,
                            output_name=cst.MASK_SEG,
                            ),
        settings_model=SegmentSettings,
        item_runner=segment,
        pool="gpu"
    ),
    StepName.TRACK: StepSpec(
        profile=StepProfile(step_name=StepName.TRACK,
                            distribution=cst.DIST_TRACK,
                            input_artifact=cst.ARTI_SEG,
                            additional_artifacts=(cst.ARTI_IMG,),
                            output_artifact=cst.ARTI_TRACK,
                            output_name=cst.MASK_TRACK,
                            ),
        settings_model=TrackSettings,
        item_runner=track,
        pool="gpu"
    ),
    StepName.EDIT_TRACK: StepSpec(
        profile=StepProfile(step_name=StepName.EDIT_TRACK,
                            distribution=cst.DIST_PIPELINE,
                            input_artifact=cst.ARTI_TRACK,
                            additional_artifacts=(cst.ARTI_IMG,),
                            output_artifact=cst.ARTI_TRACK,
                            output_name=cst.MASK_TRACK_EDITED,
                            ),
        settings_model=EditTrackSettings,
        item_runner=None,
        pool="cpu",
        kind="interactive",
        max_concurrency=1,
    ),
    StepName.EXTRACT: StepSpec(
        profile=StepProfile(step_name=StepName.EXTRACT,
                            distribution=cst.DIST_EXTRACT,
                            input_artifact=cst.ARTI_IMG,
                            output_artifact=cst.ARTI_QUANTI,
                            output_name=cst.QUANTI_NAME,
                            ),
        settings_model=ExtractSettings,
        item_runner=extract,
        pool="cpu",
        max_concurrency=1
    ),
    StepName.DISTANCE_PROFILE: StepSpec(
        profile=StepProfile(step_name=StepName.DISTANCE_PROFILE,
                            distribution=cst.DIST_DISTANCE_PROFILE,
                            input_artifact=cst.ARTI_IMG,
                            output_artifact=cst.ARTI_DIST_PROF,
                            output_name=cst.DISTANCE_PROFILE_NAME,
                            ),
        settings_model=DistanceProfileSettings,
        item_runner=run_distance_profile,
        pool="cpu",
    ),
}


# Default profiles also follow the current flow when used outside a configured run.
# Configured execution narrows these alternatives to the latest enabled producer.
_images: list[str] = []
for _step in cst.WORKFLOW_ORDER:
    _spec = REGISTRY[_step]
    if _spec.profile.input_artifact == cst.ARTI_IMG:
        _spec = replace(_spec, profile=replace(_spec.profile,
                        input_artifact=_images[-1],
                        input_alternatives=tuple(reversed(_images[:-1]))))
        REGISTRY[_step] = _spec
    if _step in cst.IMAGE_OUTPUTS:
        _images.append(cst.IMAGE_OUTPUTS[_step])
