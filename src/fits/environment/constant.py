from __future__ import annotations

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
        StepName.REGISTER_CHANNEL,
        StepName.REGISTER_TIME,
        StepName.BG_SUB,
        StepName.SEGMENT,
        StepName.TRACK,
        StepName.EDIT_TRACK,
        StepName.DISTANCE_PROFILE,
        StepName.EXTRACT,
        )


DIST_FITS = "fits"
DIST_IO = "fits-io"
DIST_REGISTER = "stackalign"
DIST_BG_SUB = "bg-sub"
DIST_SEG = "cellpose-kit"
DIST_TRACK = "tracklink"
DIST_EXTRACT = "bioimagequant"
DIST_DISTANCE_PROFILE = "bioimagequant"

FitsName = Literal["fits_array_raw.tif", "fits_array_reg_channel.tif", "fits_array_reg.tif", "fits_array_bgsub.tif", "fits_masks_seg.tif", "fits_masks_track.tif", "fits_masks.tif", "fits_array.tif", "fits_mask.tif", "fits_track.tif", "fits_track_edited.tif", "fits_track_edited_filtered.tif", "fits_distance_profile.parquet", "fits_quantification.parquet"]
FITS_ARRAY_NAME = "fits_array.tif"
FITS_ARRAY_RAW = "fits_array_raw.tif"
FITS_ARRAY_REG_CHANNEL = "fits_array_reg_channel.tif"
FITS_ARRAY_REG_TIME = "fits_array_reg.tif"
FITS_ARRAY_BGSUB = "fits_array_bgsub.tif"
FITS_MASKS_COMPACTED = "fits_masks.tif"
FITS_MASK_SEG = "fits_masks_seg.tif"
FITS_MASK_TRACK = "fits_masks_track.tif"
FITS_COMPATIBLE_VERSION = "4.0.0"
ARTI_IMG_RAW = "image_raw"
ARTI_IMG_CHANNEL = "image_channel_registered"
ARTI_IMG_TIME = "image_time_registered"
ARTI_IMG_BGSUB = "image_background_subtracted"
ARTI_IMG_COMPACTED = "image_compacted"
ARTI_MASK_COMPACTED = "mask_compacted"
IMAGE_STAGE_ARTIFACTS = (ARTI_IMG_RAW, ARTI_IMG_CHANNEL, ARTI_IMG_TIME, ARTI_IMG_BGSUB)
IMAGE_STAGE_NAMES = (FITS_ARRAY_RAW, FITS_ARRAY_REG_CHANNEL, FITS_ARRAY_REG_TIME, FITS_ARRAY_BGSUB)
IMAGE_NAMES = (FITS_ARRAY_NAME, *IMAGE_STAGE_NAMES)
SEGMENTATION_NAMES = (FITS_MASK_SEG, "fits_mask.tif")
TRACKING_NAMES = (FITS_MASK_TRACK, "fits_track.tif", "fits_track_edited.tif", "fits_track_edited_filtered.tif")
MASK_NAMES = (*SEGMENTATION_NAMES, *TRACKING_NAMES, FITS_MASKS_COMPACTED)
COMPARTMENT_MASK_NAMES = tuple(f"{name[:-4]}_{compartment}.tif"
                               for name in MASK_NAMES for compartment in ("mb", "cyto"))
LEGACY_RESULT_NAMES = (FITS_ARRAY_NAME, *SEGMENTATION_NAMES[1:], TRACKING_NAMES[1])
FITS_REFERENCE_TEMPLATE = "fits_ref_{label}.tif"
FITS_ROI_TEMPLATE = "fits_roi_{label}.tif"
FITS_MASK_TRACK_EDITED = "fits_track_edited.tif"
FITS_MASK_TRACK_EDITED_FILTERED = "fits_track_edited_filtered.tif"
FITS_TRACK_OVERLAY_PREFIX = "fits_track_overlay"
FITS_DISTANCE_PROFILE_NAME = "fits_distance_profile.parquet"
FITS_QUANTI_NAME = "fits_quantification.parquet"
MANAGED_NAMES = tuple(dict.fromkeys((*IMAGE_NAMES, *MASK_NAMES, *COMPARTMENT_MASK_NAMES,
                                   FITS_DISTANCE_PROFILE_NAME, FITS_QUANTI_NAME)))
FITS_FILES = set(MANAGED_NAMES)

EXCLUDED_PREFIXES = {'fits_'}

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
