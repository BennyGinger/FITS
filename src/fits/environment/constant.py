
from typing import Literal


STEP_CONVERT = "convert"

DIST_IO = "fits-io"

FITS_ARRAY_NAME = "fits_array.tif"
FITS_MASK_NAME = "fits_mask.tif"
FITS_FILES = {FITS_ARRAY_NAME, FITS_MASK_NAME}

EXCLUDED_PREFIXES = {'fits_'}

Mode = Literal["cli", "gui", "notebook"]