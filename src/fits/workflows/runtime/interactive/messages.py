"""Messages exchanged between the interactive workflow and mask-drawing UI.

The workflow creates a :class:`MaskCollectionRequest` when an experiment is
ready for manual mask collection. The GUI consumes that request and returns a
:class:`MaskCollectionOutcome` describing the saved and skipped masks.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fits.settings.models import DistanceProfileSettings, ExtractSettings


@dataclass(frozen=True)
class MaskCollectionRequest:
    """
    Describe the masks that the GUI should collect for one prepared image.

    Requests are derived from enabled extraction and distance-profile settings,
    then queued in ``MaskCollectionWindow`` by the interactive workflow.
    """
    experiment_id: str
    image_path: Path
    expected_ref_masks: int = 1
    expected_roi_masks: int = 0
    requires_reference: bool = True
    uses_roi: bool = True

    def __post_init__(self) -> None:
        """
        Normalize the image path and reject invalid expected-mask counts.
        """
        object.__setattr__(self, "image_path", Path(self.image_path).resolve())
        if self.expected_ref_masks < 0 or self.expected_roi_masks < 0:
            raise ValueError("Expected mask counts cannot be negative.")

    @classmethod
    def from_settings(cls, image_path: Path, *, extraction: ExtractSettings | None = None,
                      profile: DistanceProfileSettings | None = None) -> MaskCollectionRequest:
        """
        Build a collection request from the enabled downstream task settings.
        """
        refs = max(extraction.expected_ref_masks if extraction and extraction.draw_ref_mask else 0,
                   profile.expected_ref_masks if profile else 0)
        rois = profile.expected_roi_masks if profile and profile.draw_roi_mask else 0
        return cls(experiment_id=image_path.parent.name,
                   image_path=image_path,
                   expected_ref_masks=refs,
                   expected_roi_masks=rois,
                   requires_reference=profile is not None,
                   uses_roi=profile is not None)


@dataclass(frozen=True)
class MaskCollectionOutcome:
    """
    Report the mask files produced after the GUI finishes one request.

    The interactive workflow validates these paths and uses the skipped counts
    to distinguish deliberately omitted masks from unfinished collection.
    """
    request: MaskCollectionRequest
    reference_paths: tuple[Path, ...]
    roi_paths: tuple[Path, ...]
    skipped_references: int
    skipped_rois: int
