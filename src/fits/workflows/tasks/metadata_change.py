from pathlib import Path
from typing import Sequence
import logging

from fits_io import FitsIO
from fits_io.readers._types import StatusFlag

from fits.environment.constant import FITS_FILES


logger = logging.getLogger(__name__)


def _collect_fits_files(exp_dirs: Path | Sequence[Path], recursive: bool) -> list[Path]:
    if isinstance(exp_dirs, Path):
        exp_dirs = [exp_dirs]
    else:
        exp_dirs = list(exp_dirs)

    files: list[Path] = []
    for exp_dir in exp_dirs:
        for fits_name in FITS_FILES:
            if recursive:
                found_files = list(exp_dir.rglob(fits_name))
            else:
                found_files = list(exp_dir.glob(fits_name))
            files.extend(found_files)

    return files


def change_status(exp_dirs: Path | Sequence[Path], new_status: StatusFlag, recursive: bool = False) -> None:
    """
    Change the status of one or more experiments to either 'active' or 'skip'.
    
    Args:
        exp_dirs: A single experiment directory or a list of experiment directories to process. The function will look for FITS files in these directories and their subdirectories.
        new_status: The new status to set for the FITS files. Must be either 'active' or 'skip'.
        recursive: Whether to search for FITS files recursively in subdirectories. Default is False.
    
    Policy:
    - This function will only change the status in the metadata, so it will load whatever array is already stored in the file and re-save it with updated metadata. So, no z-projection, channel labels, compression or provenance tag is applied here.
    - Multi-series inputs are not supported here by design.
    """
    files = _collect_fits_files(exp_dirs, recursive=recursive)
    logger.info(f"Changing status of {len(files)} files to {new_status}")
    logger.debug(f"Files to update: {files}")
            
    for file in files:
        reader = FitsIO.from_path(file)
        reader.set_status(new_status)


def change_labels(exp_dirs: Path | Sequence[Path], new_labels: str | Sequence[str], recursive: bool = False) -> None:
    """
    Change the channel labels of one or more experiments.
    
    Args:
        exp_dirs: A single experiment directory or a list of experiment directories to process. The function will look for FITS files in these directories and their subdirectories.
        new_labels: The new channel labels to set in the metadata, either a single string for one channel or a sequence of strings for multiple channels.
        recursive: Whether to search for FITS files recursively in subdirectories. Default is False.
    
    Policy:
    - This function will only change the channel labels in the metadata, so it will load whatever array is already stored in the file and re-save it with updated metadata. So, no z-projection, change status, compression or provenance tag is applied here.
    - Multi-series inputs are not supported here by design.
    """
    files = _collect_fits_files(exp_dirs, recursive=recursive)
    logger.info(f"Changing labels of {len(files)} files to {new_labels}")
    logger.debug(f"Files to update: {files}")
            
    for file in files:
        reader = FitsIO.from_path(file)
        reader.set_channel_labels(new_labels)
