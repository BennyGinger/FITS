from __future__ import annotations

from fisch.environment import naming

from collections.abc import Callable, Sequence
from typing import Any, Literal
from enum import StrEnum
from numpy.typing import NDArray
import numpy as np


class StepName(StrEnum):
    CONVERT = "convert"
    REGISTER_TIME = "register_time"
    REGISTER_CHANNEL = "register_channel"
    BG_SUB = "bg_sub"
    SEGMENT = "segment"
    TRACK = "track"
    EDIT_TRACK = "edit_track"
    EXTRACT = "extract"
    DISTANCE_PROFILE = "distance_profile"

WORKFLOW_ORDER: tuple[StepName, ...] = (
        StepName.CONVERT,
        StepName.BG_SUB,
        StepName.REGISTER_CHANNEL,
        StepName.REGISTER_TIME,
        StepName.SEGMENT,
        StepName.TRACK,
        StepName.EDIT_TRACK,
        StepName.DISTANCE_PROFILE,
        StepName.EXTRACT,
        )


DIST_PIPELINE = "fisch"
DIST_IO = "scope-io"
DIST_REGISTER = "stackalign"
DIST_BG_SUB = "bg-sub"
DIST_SEG = "cellpose-kit"
DIST_TRACK = "tracklink"
DIST_EXTRACT = "bioimagequant"
DIST_DISTANCE_PROFILE = "bioimagequant"

ArtifactName = Literal["proc_array_raw.tif", "proc_array_reg_channel.tif", "proc_array_reg.tif", "proc_array_bgsub.tif", "proc_masks_seg.tif", "proc_masks_track.tif", "proc_masks.tif", "proc_array.tif", "proc_mask.tif", "proc_track.tif", "proc_track_edited.tif", "proc_track_edited_filtered.tif", "proc_distance_profile.parquet", "proc_quantification.parquet"]
ARRAY_NAME = naming.CURRENT_IMAGES[0]
ARRAY_RAW = naming.CURRENT_IMAGES[1]
ARRAY_REG_CHANNEL = naming.CURRENT_IMAGES[2]
ARRAY_REG_TIME = naming.CURRENT_IMAGES[3]
ARRAY_BGSUB = naming.CURRENT_IMAGES[4]
MASKS_COMPACTED = naming.CURRENT_MASKS[2]
MASK_SEG = naming.CURRENT_MASKS[0]
MASK_TRACK = naming.CURRENT_MASKS[1]
COMPATIBLE_VERSION = "5.0.0"
ARTI_IMG_RAW = "image_raw"
ARTI_IMG_CHANNEL = "image_channel_registered"
ARTI_IMG_TIME = "image_time_registered"
ARTI_IMG_BGSUB = "image_background_subtracted"
ARTI_IMG_COMPACTED = "image_compacted"
ARTI_MASK_COMPACTED = "mask_compacted"
# Output identities are fixed; their processing and presentation order is not.
IMAGE_OUTPUTS = {
    StepName.CONVERT: ARTI_IMG_RAW,
    StepName.REGISTER_CHANNEL: ARTI_IMG_CHANNEL,
    StepName.REGISTER_TIME: ARTI_IMG_TIME,
    StepName.BG_SUB: ARTI_IMG_BGSUB,
}
IMAGE_OUTPUT_NAMES = {
    StepName.CONVERT: ARRAY_RAW,
    StepName.REGISTER_CHANNEL: ARRAY_REG_CHANNEL,
    StepName.REGISTER_TIME: ARRAY_REG_TIME,
    StepName.BG_SUB: ARRAY_BGSUB,
}


def validate_workflow_order() -> None:
    """Allow preprocessing permutations while rejecting broken stage dependencies."""
    if len(WORKFLOW_ORDER) != len(StepName) or set(WORKFLOW_ORDER) != set(StepName):
        raise ValueError("WORKFLOW_ORDER must contain every step exactly once.")
    position = {step: index for index, step in enumerate(WORKFLOW_ORDER)}
    dependencies = [(StepName.CONVERT, step) for step in StepName if step != StepName.CONVERT]
    dependencies += [(step, StepName.SEGMENT) for step in IMAGE_OUTPUTS if step != StepName.CONVERT]
    dependencies += [(StepName.SEGMENT, StepName.TRACK), (StepName.TRACK, StepName.EDIT_TRACK)]
    dependencies += [(StepName.EDIT_TRACK, step) for step in (StepName.EXTRACT, StepName.DISTANCE_PROFILE)]
    for before, after in dependencies:
        if position[before] >= position[after]:
            raise ValueError(f"Invalid WORKFLOW_ORDER: {before} must precede {after}.")


validate_workflow_order()
IMAGE_STEPS = tuple(step for step in WORKFLOW_ORDER if step in IMAGE_OUTPUTS)
IMAGE_STAGE_ARTIFACTS = tuple(IMAGE_OUTPUTS[step] for step in IMAGE_STEPS)
IMAGE_STAGE_NAMES = tuple(IMAGE_OUTPUT_NAMES[step] for step in IMAGE_STEPS)
IMAGE_NAMES = (*naming.CURRENT_IMAGES, *naming.LEGACY_IMAGES)
SEGMENTATION_NAMES = (MASK_SEG, *(name for name, target in naming.LEGACY_FILES.items() if target == MASK_SEG))
UNEDITED_TRACKING_NAMES = (MASK_TRACK, *(name for name, target in naming.LEGACY_FILES.items() if target == MASK_TRACK))
TRACKING_NAMES = (*UNEDITED_TRACKING_NAMES, *naming.CURRENT_MASKS[3:],
                  *(name for name, target in naming.LEGACY_FILES.items() if target in naming.CURRENT_MASKS[3:]))
MASK_NAMES = (*SEGMENTATION_NAMES, *TRACKING_NAMES, MASKS_COMPACTED)
COMPARTMENT_MASK_NAMES = tuple(f"{name[:-4]}_{compartment}.tif"
                               for name in MASK_NAMES for compartment in ("mb", "cyto"))
LEGACY_RESULT_NAMES = (*naming.LEGACY_IMAGES, *naming.LEGACY_MASKS)
REFERENCE_TEMPLATE = naming.REFERENCE
ROI_TEMPLATE = naming.ROI
MASK_TRACK_EDITED = naming.CURRENT_MASKS[3]
MASK_TRACK_EDITED_FILTERED = naming.CURRENT_MASKS[4]
TRACK_OVERLAY_PREFIX = naming.OVERLAY
DISTANCE_PROFILE_NAME = naming.CURRENT_TABLES[1]
QUANTI_NAME = naming.CURRENT_TABLES[0]
MANAGED_NAMES = tuple(dict.fromkeys((*IMAGE_NAMES, *MASK_NAMES, *COMPARTMENT_MASK_NAMES,
                                   DISTANCE_PROFILE_NAME, QUANTI_NAME, *naming.LEGACY_FILES)))
FILES = set(MANAGED_NAMES)

EXCLUDED_PREFIXES = {naming.PREFIX, naming.LEGACY_PREFIX}

ExecMode = Literal["serial", "thread", "process"]

RunTimeMode = Literal["batch", "conveyor"]

ArtifactType = Literal["image_compacted", "mask_compacted", "image_raw", "image_channel_registered", "image_time_registered", "image_background_subtracted", "raw_image", "image", "reference_mask", "roi_mask", "segmentation", "tracking", "quantification", "distance_profile"]
ARTI_RAW = "raw_image"
ARTI_IMG = "image"
ARTI_REF = "reference_mask"
ARTI_ROI = "roi_mask"
ARTI_SEG = "segmentation"
ARTI_TRACK = "tracking"
ARTI_DIST_PROF = "distance_profile"
ARTI_QUANTI = "quantification"
MASTER_QUANTI_NAME = "master_quantification.parquet"
MASTER_DISTANCE_PROFILE_NAME = "master_distance_profile.parquet"
MASTER_TABLES: tuple[tuple[ArtifactType, str], ...] = (
    (ARTI_QUANTI, MASTER_QUANTI_NAME),
    (ARTI_DIST_PROF, MASTER_DISTANCE_PROFILE_NAME),
)


ChannelScope = Literal['all'] | Sequence[int] | None


RegistrationMode = Literal["time", "channel"]
RegistrationAlgorithm = Literal["scikit", "pystackreg", "cv2"]
RegistrationMethod = Literal["translation", "rigid_body", "affine"]
TimeRegiContext = Literal[
    "linear_drift",
    "rotational_drift",
    "complex_drift",
]
ChannelRegiContext = Literal[
    "channel_shift",
    "channel_shift_dual_cam",
    "channel_shift_complex",
]
RegistrationContext = TimeRegiContext | ChannelRegiContext

STATISTIC_MAP: dict[str, Callable[..., NDArray[Any]]] = {
    "median": np.median,
    "mean": np.mean,
}
SUPPORTED_STATISTICS = set(STATISTIC_MAP.keys())
