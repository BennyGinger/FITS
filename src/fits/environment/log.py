from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal


LevelName = Literal["debug", "info", "warning", "error", "critical"]

_LEVEL_MAP: dict[LevelName, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def configure_logging(
    *,
    log_dir: Path | None,
    console_level: LevelName = "info",
    file_level: LevelName = "debug",
) -> None:
    """
    Configure global logging for the FITS pipeline.

    This function should be called once from the top-level CLI entry point.

    Parameters
    ----------
    log_dir:
        Optional directory in which to write log files.
    console_level:
        Verbosity shown in the console.
    file_level:
        Verbosity written to the log file.
    """
    root = logging.getLogger()

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    root.propagate = False

    # Let all records flow through the root logger.
    # Individual handlers decide which levels to emit.
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(_LEVEL_MAP[console_level])
    console_handler.set_name("fits_console")
    root.addHandler(console_handler)

    if log_dir is not None:
        if "log" not in log_dir.name.lower():
            log_dir = log_dir / "logs"

        log_dir.mkdir(parents=True, exist_ok=True)

        log_path = log_dir / f"fits_{datetime.now():%Y%m%d_%H%M%S}.log"

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(_LEVEL_MAP[file_level])
        file_handler.set_name("fits_file")
        root.addHandler(file_handler)

    # Reduce verbosity of noisy third-party loggers by default.
    _quiet_logger("cellpose")
    _quiet_logger("fits_io.readers.r_nd2", logging.ERROR)
    _quiet_logger("numba")
    _quiet_logger("numcodecs")
    _quiet_logger("hydra.core.utils")
    _quiet_logger("trackastra.model.model_api")


def _quiet_logger(
    name: str,
    level: int = logging.WARNING,
) -> None:
    logging.getLogger(name).setLevel(level)