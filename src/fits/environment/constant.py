
from collections.abc import Callable
from typing import Any, Literal

from numpy.typing import NDArray
import numpy as np


STEP_CONVERT = "convert"
STEP_REGISTER_TIME = "register_time"
STEP_REGISTER_CHANNEL = "register_channel"
STEP_BG_SUB = "bg_sub"
STEP_SEGMENT = "segment"

WORKFLOW_ORDER = [
    STEP_CONVERT,
    STEP_REGISTER_TIME,
    STEP_REGISTER_CHANNEL,
    STEP_BG_SUB,
    STEP_SEGMENT,
]

DIST_IO = "fits-io"
DIST_REGISTER = "stackalign"
DIST_BG_SUB = "bg-sub"
DIST_SEG = "cellpose-kit"

FitsName = Literal["fits_array.tif", "fits_mask.tif"]
FITS_ARRAY_NAME = "fits_array.tif"
FITS_MASK_NAME = "fits_mask.tif"
FITS_FILES: set[FitsName] = {FITS_ARRAY_NAME, FITS_MASK_NAME}

EXCLUDED_PREFIXES = {'fits_'}

UIMode = Literal["cli", "gui", "notebook"]

ExecMode = Literal["serial", "thread", "process"]

RunTimeMode = Literal["batch", "conveyor"]

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