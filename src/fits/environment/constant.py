
from typing import Literal


STEP_CONVERT = "convert"
STEP_SEGMENT = "segment"

DIST_IO = "fits-io"
DIST_SEG = "cellpose-kit"

FitsName = Literal["fits_array.tif", "fits_mask.tif"]
FITS_ARRAY_NAME = "fits_array.tif"
FITS_MASK_NAME = "fits_mask.tif"
FITS_FILES: set[FitsName] = {FITS_ARRAY_NAME, FITS_MASK_NAME}

EXCLUDED_PREFIXES = {'fits_'}

UIMode = Literal["cli", "gui", "notebook"]

ExecMode = Literal["serial", "thread", "process"]