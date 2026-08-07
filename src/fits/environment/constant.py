
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

WORKFLOW_ORDER: tuple[StepName, ...] = (
        StepName.CONVERT,
        StepName.REGISTER_TIME,
        StepName.REGISTER_CHANNEL,
        StepName.BG_SUB,
        StepName.SEGMENT,
        StepName.TRACK,
        )


DIST_FITS = "fits"
DIST_IO = "fits-io"
DIST_REGISTER = "stackalign"
DIST_BG_SUB = "bg-sub"
DIST_SEG = "cellpose-kit"
DIST_TRACK = "tracklink"

FitsName = Literal["fits_array.tif", "fits_mask.tif", "fits_track.tif"]
FITS_ARRAY_NAME = "fits_array.tif"
FITS_MASK_SEG = "fits_mask.tif"
FITS_MASK_TRACK = "fits_track.tif"
FITS_FILES: set[FitsName] = {FITS_ARRAY_NAME, FITS_MASK_SEG, FITS_MASK_TRACK}

EXCLUDED_PREFIXES = {'fits_'}

ExecMode = Literal["serial", "thread", "process"]

RunTimeMode = Literal["batch", "conveyor"]

ArtifactType = Literal["raw_image", "image", "segmentation", "tracking"]
ARTI_RAW = "raw_image"
ARTI_IMG = "image"
ARTI_SEG = "segmentation"
ARTI_TRACK = "tracking"


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