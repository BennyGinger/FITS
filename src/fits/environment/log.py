from __future__ import annotations
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Literal

try:
    from PySide6.QtCore import QObject, Signal
    PYSIDE_AVAILABLE = True
except ImportError:
    QObject = None
    Signal = None
    PYSIDE_AVAILABLE = False

from fits.environment.constant import Mode


LevelName = Literal["debug", "info", "warning", "error", "critical"]

_LEVEL_MAP: dict[LevelName, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

# ---------------------------------------------------------------------
# GUI logging (Qt handler)
# ---------------------------------------------------------------------

if PYSIDE_AVAILABLE and QObject is not None and Signal is not None:

    class LogEmitter(QObject):
        """
        QObject living in the main GUI thread.
        Emits formatted log messages via Qt signals.
        """
        message = Signal(str)

    class QtLogHandler(logging.Handler):
        """
        Thread-safe logging handler that forwards records
        to a Qt signal (safe for background threads).
        """

        def __init__(self, emitter: LogEmitter):
            super().__init__()
            self._emitter = emitter

        def emit(self, record: logging.LogRecord) -> None:
            try:
                msg = self.format(record)
                self._emitter.message.emit(msg)
            except Exception:
                self.handleError(record)


else:
    # Dummy placeholders so type-checkers don’t complain
    LogEmitter = None # type: ignore
    QtLogHandler = None # type: ignore

# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def configure_logging(*, log_dir: Path | None, mode: Mode = "cli", console_level: LevelName = "info", file_level: LevelName = "debug", gui_emitter: LogEmitter | None = None,) -> None:
    """
    Configure global logging for the FITS pipeline.

    This function should be called ONCE at the top-level
    entry point (CLI / GUI / notebook).

    Parameters
    ----------
    log_dir:
        Optional directory to write log files to
    mode:
        Execution mode ("cli", "gui", "notebook")
    console_level:
        Verbosity shown in console / notebook / GUI
    file_level:
        Verbosity written to log file
    gui_emitter:
        Required for GUI mode; receives log messages via Qt signals
    """
    
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.propagate = False

    # Let everything flow; handlers decide what to show.
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    # Console / notebook
    if mode == "gui" and gui_emitter is not None:
        if gui_emitter is None:
            raise ValueError("GUI mode requires a LogEmitter instance")
        
        if not PYSIDE_AVAILABLE:
            raise RuntimeError("PySide6 is not available but GUI mode was requested")

        handler: logging.Handler = QtLogHandler(gui_emitter)
    else:
        # CLI & notebook use stdout
        handler = logging.StreamHandler(sys.stdout)
    
    handler.setFormatter(fmt)
    handler.setLevel(_LEVEL_MAP[console_level])
    handler.set_name("fits_console")
    root.addHandler(handler)
    

    # Optional file
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"fits_{datetime.now():%Y%m%d_%H%M%S}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.setLevel(_LEVEL_MAP[file_level])
        file_handler.set_name("fits_file")
        root.addHandler(file_handler)
