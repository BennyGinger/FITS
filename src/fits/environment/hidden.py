"""Best-effort Windows visibility attributes; never change file permissions."""

import ctypes
from ctypes import wintypes
import logging
from pathlib import Path
import stat
import sys


logger = logging.getLogger(__name__)


def _set_hidden_attribute(path: Path, attributes: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_attributes = kernel32.SetFileAttributesW
    set_attributes.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    set_attributes.restype = wintypes.BOOL
    filename = str(path.absolute())
    # Support long local paths and network shares as well as ordinary paths.
    if not filename.startswith("\\\\?\\"):
        filename = "\\\\?\\UNC\\" + filename[2:] if filename.startswith("\\\\") else "\\\\?\\" + filename
    # NORMAL is only valid alone; retain all other existing attributes.
    attributes = (attributes & ~stat.FILE_ATTRIBUTE_NORMAL) | stat.FILE_ATTRIBUTE_HIDDEN
    if not set_attributes(filename, attributes):
        raise ctypes.WinError(ctypes.get_last_error())


def hide_on_windows(path: Path) -> bool:
    """Hide an existing entry on Windows; return False if attributes cannot be set.

    Other platforms do nothing. A missing path or unsupported/read-only share
    never interrupts installation, processing, or a viewer's cache fallback.
    """
    if sys.platform != "win32":
        return True
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
        if not attributes & stat.FILE_ATTRIBUTE_HIDDEN:
            _set_hidden_attribute(path, attributes)
    except OSError:
        logger.debug("Could not hide internal FITS entry %s", path, exc_info=True)
        return False
    return True
