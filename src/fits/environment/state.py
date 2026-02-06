from dataclasses import dataclass, replace
from pathlib import Path
from typing_extensions import Literal

from fits.environment.context import ExecutionContext



@dataclass(frozen=True)
class ExperimentState():
    """
    Main wrapper for experiment state information during pipeline execution.
    
    Attributes:
        image: Path to the main experiment image.
        masks: Optional Path to the masks used in the experiment.
        last_step: Optional name of the last completed step in the pipeline, used for resuming or tracking progress.
    """
    
    image: Path
    masks: Path | None = None
    last_step: str | None = None
    
    def replace(self, **kwargs) -> "ExperimentState":
        """
        Create a new ExperimentState with updated fields. This method allows for immutability while still enabling updates to the state.
        
        Example usage:
            new_state = old_state.replace(image=new_image_path)"""
        return replace(self, **kwargs)