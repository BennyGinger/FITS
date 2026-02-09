from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fits_io.client import FitsIO



@dataclass(frozen=True)
class ExperimentState():
    """
    Main wrapper for experiment state information during pipeline execution.
    
    Attributes:
        original_image: Path to the original image file.
        image: Optional Path to the FITS experiment image.
        masks: Optional Path to the FITS experiment masks.
        last_step: Optional name of the last completed step in the pipeline, used for resuming or tracking progress.
    """
    
    original_image: Path
    image: Path | None = None
    masks: Path | None = None
    last_step: str | None = None
    
    def replace(self, **kwargs) -> "ExperimentState":
        """
        Create a new ExperimentState with updated fields. This method allows for immutability while still enabling updates to the state.
        
        Example usage:
            new_state = old_state.replace(image=new_image_path)"""
        return replace(self, **kwargs)
    
    @property
    def workdir(self) -> Path | None:
        """
        Get the working directory for the experiment, which is the parent directory of the FITS array.
        """
        return self.image.parent if self.image is not None and isinstance(self.image, Path) else None
    
    def load_custom_metadata(self) -> dict[str, Any]:
        """
        Get the custom metadata from the image file, if available.
        """
        if self.image is None or not isinstance(self.image, Path):
            return {}
        
        reader = FitsIO.from_path(self.image)
        meta = dict(reader.fits_metadata)
        
        if self.masks is not None and isinstance(self.masks, Path):
            mask_reader = FitsIO.from_path(self.masks)
            mask_meta = dict(mask_reader.fits_metadata)
            # Merge metadata, with mask metadata taking precedence in case of conflicts
            meta.update(mask_meta)
        return meta
    
        