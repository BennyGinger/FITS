from dataclasses import dataclass
from typing import Literal

from fits.environment.constant import Mode


@dataclass
class ExecutionContext:
    """Wrapper for execution context parameters used across the FITS processing pipeline.
    
    Attributes:
        user_name : Name of the user executing the pipeline.
        dry_run : If True, simulate actions without making changes.
        mode : Execution mode, can be 'cli', 'gui', or 'notebook'.
    """
    
    user_name: str
    dry_run: bool = False
    mode: Mode = "cli"
