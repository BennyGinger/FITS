"""Discovery of supported raw experiment inputs."""

from __future__ import annotations

import logging
from pathlib import Path
from scope_io import SUPPORTED_EXTENSIONS
from fits.environment.constant import EXCLUDED_PREFIXES
from fits.environment.paths import INTERNAL_DIR_NAMES


logger = logging.getLogger(__name__)


def collect_supported_files(directory: Path) -> list[Path]:
    """
    Return supported image files found recursively below a directory.
    """
    prefixes = tuple(EXCLUDED_PREFIXES)
    extensions = {extension.lower() for extension in SUPPORTED_EXTENSIONS}
    supported_files: set[Path] = set()
    for path in directory.rglob("*"):
        if any(part in INTERNAL_DIR_NAMES for part in path.relative_to(directory).parts):
            continue
        if not path.is_file():
            continue
        if path.name.startswith(prefixes):
            continue
        if path.suffix.lower() in extensions:
            supported_files.add(path)
            logger.debug("Found supported file: %s", path)
    return sorted(supported_files)
