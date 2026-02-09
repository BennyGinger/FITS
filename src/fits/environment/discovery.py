import logging

from pathlib import Path
from fits_io import SUPPORTED_EXTENSIONS

from fits.environment.constant import EXCLUDED_PREFIXES, FITS_FILES


logger = logging.getLogger(__name__)


def collect_supported_files(directory: Path) -> list[Path]:
    """
    Collect all supported image files under a directory.

    Returns:
        Sorted list of image file paths.
    """
    prefixes = tuple(EXCLUDED_PREFIXES)
    exts = {e.lower() for e in SUPPORTED_EXTENSIONS}
    
    supported_files: set[Path] = set()
    for p in directory.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith(prefixes):
            continue
        if p.suffix.lower() in exts:
            supported_files.add(p)
            logger.debug(f"Found supported file: {p}")
    
    return sorted(supported_files)

def find_fits_outputs(directory: Path) -> list[Path]:
    """
    Find all FITS files output (by expected filenames) in a directory and its subdirectories.
    
    Args:
        directory: Path to the directory to search.
    """
    fits_files: set[Path] = set()
    for p in directory.rglob("*"):
        if not p.is_file():
            continue
        if p.name.lower() in FITS_FILES:
            fits_files.add(p)
            logger.debug(f"Found FITS output file: {p}")
    return sorted(fits_files)







if __name__ == "__main__":
    
    
    for tag in SUPPORTED_EXTENSIONS:
        print(tag)