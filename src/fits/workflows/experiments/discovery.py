"""Discovery of supported raw experiment inputs."""

import logging
from pathlib import Path

from fits_io import SUPPORTED_EXTENSIONS

from fits.environment.constant import EXCLUDED_PREFIXES


logger = logging.getLogger(__name__)


def collect_supported_files(directory: Path) -> list[Path]:
    """
    Return supported image files found recursively below a directory.
    """
    prefixes = tuple(EXCLUDED_PREFIXES)
    extensions = {extension.lower() for extension in SUPPORTED_EXTENSIONS}
    supported_files: set[Path] = set()
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith(prefixes):
            continue
        if path.suffix.lower() in extensions:
            supported_files.add(path)
            logger.debug("Found supported file: %s", path)
    return sorted(supported_files)
