"""Plain requests and outcomes shared by mask collection and its caller."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fits.settings.models import DistanceProfileSettings, ExtractSettings


@dataclass(frozen=True)
class MaskCollectionRequest:
    experiment_id: str
    image_path: Path
    expected_ref_masks: int = 1
    expected_roi_masks: int = 0
    requires_reference: bool = True
    uses_roi: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "image_path", Path(self.image_path).resolve())
        if self.expected_ref_masks < 0 or self.expected_roi_masks < 0:
            raise ValueError("Expected mask counts cannot be negative.")

    @classmethod
    def from_settings(cls, image_path: Path, *, extraction: ExtractSettings | None = None,
                      profile: DistanceProfileSettings | None = None) -> MaskCollectionRequest:
        refs = max(extraction.expected_ref_masks if extraction and extraction.draw_ref_mask else 0,
                   profile.expected_ref_masks if profile else 0)
        rois = profile.expected_roi_masks if profile and profile.draw_roi_mask else 0
        return cls(image_path.parent.name, image_path, refs, rois,
                   requires_reference=profile is not None, uses_roi=profile is not None)


@dataclass(frozen=True)
class MaskCollectionOutcome:
    request: MaskCollectionRequest
    reference_paths: tuple[Path, ...]
    roi_paths: tuple[Path, ...]
    skipped_references: int
    skipped_rois: int


