from typing import Callable, Sequence
import logging

from pathlib import Path
from fits_io import SUPPORTED_EXTENSIONS

from fits.environment.constant import EXCLUDED_PREFIXES, FITS_FILES


logger = logging.getLogger(__name__)




def _rglob(directory: Path, pattern: str) -> list[Path]:
    """
    Recursively glob for files matching pattern in directory.
    """
    return list(directory.rglob(pattern))

def collect_supported_files(directory: Path) -> list[Path]:
    """
    Find all supported image files in a directory and its subdirectories.
    
    Args:
        directory: Path to the directory to search.
    """
    all_experiments: list[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        found_files = _rglob(directory, f"*{ext}")
        filtered_files = [f for f in found_files if not f.name.startswith(tuple(EXCLUDED_PREFIXES))]
        all_experiments.extend(filtered_files)
    return sorted(all_experiments)

def find_fits_files(directory: Path) -> list[Path]:
    """
    Find all FITS files in a directory and its subdirectories.
    
    Args:
        directory: Path to the directory to search.
    """
    fits_files: list[Path] = []
    for files_type in FITS_FILES:
        fits_files.extend(_rglob(directory, files_type))
    return sorted(fits_files)







if __name__ == "__main__":
    
    
    for tag in SUPPORTED_EXTENSIONS:
        print(tag)