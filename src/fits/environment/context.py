from dataclasses import dataclass
from pathlib import Path

from fits.environment.constant import UIMode


@dataclass
class ExecutionContext:
    """Wrapper for execution context parameters used across the FITS processing pipeline.

    Attributes:
        user_name : Name of the user executing the pipeline.
        dry_run : If True, simulate actions without making changes.
        mode : Execution mode, can be 'cli', 'gui', or 'notebook'.
        run_dir : Root directory of the current run. Runtime-only
    """

    user_name: str
    dry_run: bool = False
    mode: UIMode = "cli"
    run_dir: Path | None = None
