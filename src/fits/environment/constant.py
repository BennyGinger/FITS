
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
    EXTRACT = "extract"
    DISTANCE_PROFILE = "distance_profile"

WORKFLOW_ORDER: tuple[StepName, ...] = (
        StepName.CONVERT,
        StepName.REGISTER_TIME,
        StepName.REGISTER_CHANNEL,
        StepName.BG_SUB,
        StepName.SEGMENT,
        StepName.TRACK,
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

FitsName = Literal["fits_array.tif", "fits_mask.tif", "fits_track.tif", "fits_distance_profile.parquet", "fits_quantification.parquet"]
FITS_ARRAY_NAME = "fits_array.tif"
FITS_REFERENCE_TEMPLATE = "fits_ref_{label}.tif"
FITS_ROI_TEMPLATE = "fits_roi_{label}.tif"
FITS_MASK_SEG = "fits_mask.tif"
FITS_MASK_TRACK = "fits_track.tif"
FITS_DISTANCE_PROFILE_NAME = "fits_distance_profile.parquet"
FITS_QUANTI_NAME = "fits_quantification.parquet"
FITS_FILES: set[FitsName] = {FITS_ARRAY_NAME, FITS_MASK_SEG, FITS_MASK_TRACK, FITS_DISTANCE_PROFILE_NAME, FITS_QUANTI_NAME, }

EXCLUDED_PREFIXES = {'fits_'}

ExecMode = Literal["serial", "thread", "process"]

RunTimeMode = Literal["batch", "conveyor"]

ArtifactType = Literal["raw_image", "image", "reference_mask", "roi_mask", "segmentation", "tracking", "quantification", "distance_profile"]
ARTI_RAW = "raw_image"
ARTI_IMG = "image"
ARTI_REF = "reference_mask"
ARTI_ROI = "roi_mask"
ARTI_SEG = "segmentation"
ARTI_TRACK = "tracking"
ARTI_DIST_PROF = "distance_profile"
ARTI_QUANTI = "quantification"


ChannelScope = Literal['all'] | Sequence[int] | None


RegistrationMode = Literal["time", "channel"]
RegistrationBackend = Literal["scikit", "pystackreg", "cv2"]
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
