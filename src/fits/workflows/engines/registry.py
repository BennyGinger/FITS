from __future__ import annotations

from typing import Any

import fits.environment.constant as cst
from fits.environment.constant import StepName
from fits.settings.models import (BGSubSettings, 
                                  ConvertSettings, 
                                  RegisterChannelSettings, 
                                  RegisterTimeSettings, 
                                  SegmentSettings, 
                                  TrackSettings)
from fits.workflows.engines.models import StepProfile, StepSpec
from fits.tasks import (convert, 
                        segment, 
                        remove_bg, 
                        register_channel, 
                        register_time,
                        track)


REGISTRY: dict[str, StepSpec[Any]] = {
    StepName.CONVERT: StepSpec(
        profile=StepProfile(
            step_name=StepName.CONVERT,
            distribution=cst.DIST_IO,
            input_artifact=cst.ARTI_RAW,
            output_artifact=cst.ARTI_IMG,
            output_name=cst.FITS_ARRAY_NAME,),
        settings_model=ConvertSettings,
        item_runner=convert,
        pool="cpu"
    ),
    StepName.BG_SUB: StepSpec(
        profile=StepProfile(
            step_name=StepName.BG_SUB,
            distribution=cst.DIST_BG_SUB,
            input_artifact=cst.ARTI_IMG,
            output_artifact=cst.ARTI_IMG,
            output_name=cst.FITS_ARRAY_NAME,),
        settings_model=BGSubSettings,
        item_runner=remove_bg,
        pool="cpu"
    ),
    StepName.REGISTER_TIME: StepSpec(
        profile=StepProfile(
            step_name=StepName.REGISTER_TIME,
            distribution=cst.DIST_REGISTER,
            input_artifact=cst.ARTI_IMG,
            output_artifact=cst.ARTI_IMG,
            output_name=cst.FITS_ARRAY_NAME,),
        settings_model=RegisterTimeSettings,
        item_runner=register_time,
        pool="cpu",
        max_concurrency=1
    ),
    StepName.REGISTER_CHANNEL: StepSpec(
        profile=StepProfile(
            step_name=StepName.REGISTER_CHANNEL,
            distribution=cst.DIST_REGISTER,
            input_artifact=cst.ARTI_IMG,
            output_artifact=cst.ARTI_IMG,
            output_name=cst.FITS_ARRAY_NAME,),
        settings_model=RegisterChannelSettings,
        item_runner=register_channel,
        pool="cpu"
    ),
    StepName.SEGMENT: StepSpec(
        profile=StepProfile(
            step_name=StepName.SEGMENT,
            distribution=cst.DIST_SEG,
            input_artifact=cst.ARTI_IMG,
            output_artifact=cst.ARTI_SEG,
            output_name=cst.FITS_MASK_SEG,),
        settings_model=SegmentSettings,
        item_runner=segment,
        pool="gpu"
    ),
    StepName.TRACK: StepSpec(
        profile=StepProfile(
            step_name=StepName.TRACK,
            distribution=cst.DIST_TRACK,
            input_artifact=cst.ARTI_SEG,
            output_artifact=cst.ARTI_TRACK,
            output_name=cst.FITS_MASK_TRACK,
        ),
        settings_model=TrackSettings,
        item_runner=track,
        pool="gpu"
    ),
    }