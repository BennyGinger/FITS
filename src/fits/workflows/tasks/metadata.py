from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OutputStateMeta:
    """
    Metadata for a workflow step output.
    
    Attributes:
        output_path (str): The file path where the output is stored.
        
    """
    step: str
    axes: str = field(default_factory=str)
    channel_labels: Sequence[str] | None = None
    hashed_settings: str = field(default_factory=str)
    with_image: Path | None = None
    with_masks: Path | None = None
    mark_done: bool = False
    mark_failed: bool = False
    
    @property
    def output_labels(self) -> list[str]:
        if self.channel_labels is not None:
            return list(self.channel_labels)
        return []
    
