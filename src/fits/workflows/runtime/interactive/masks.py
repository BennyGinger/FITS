"""Determine mask requirements and validate finalized mask artifacts."""

from collections.abc import Mapping
from typing import Any

from fits.workflows.runtime.interactive.messages import (
    MaskCollectionOutcome, MaskCollectionRequest)


def interactive_masks_requested(config: Mapping[str, Any]) -> bool:
    """
    Return whether the configured workflow needs interactive mask handling.
    """
    profile = config.get('distance_profile', {})
    extraction = config.get('extract', {})
    return bool(profile.get('enabled', False) or (
        extraction.get('enabled', False)
        and extraction.get('params', {}).get('draw_ref_mask', False)))


def existing_mask_outcome(request: MaskCollectionRequest,) -> MaskCollectionOutcome:
    """
    Build an outcome from masks that currently exist beside the image.
    """
    folder = request.image_path.parent
    refs = tuple(sorted(p for p in folder.glob('fits_ref_*.tif') if p.is_file()))
    rois = tuple(sorted(p for p in folder.glob('fits_roi_*.tif') if p.is_file()))
    return MaskCollectionOutcome(
        request, refs, rois,
        max(0, request.expected_ref_masks - len(refs)),
        max(0, request.expected_roi_masks - len(rois)))


def validate_mask_outcome(request: MaskCollectionRequest, outcome: MaskCollectionOutcome,) -> None:
    """
    Check the exact mask set before tasks discover and consume those files.
    """
    from fits_io import FitsIO
    from fits.tasks.reference_mask.artifact import load_reference_artifact
    from fits.tasks.roi_mask.artifact import load_roi_artifact

    if outcome.request != request:
        raise ValueError('Mask result does not match its experiment request.')
    
    existing = existing_mask_outcome(request)
    if (set(existing.reference_paths) != set(outcome.reference_paths)
            or set(existing.roi_paths) != set(outcome.roi_paths)):
        raise ValueError(f'Mask files changed after finalization for {request.image_path}.')
    
    reader = FitsIO.from_path(request.image_path)
    loaded = reader.get_array()
    for paths, loader in ((outcome.reference_paths, load_reference_artifact),
                        (outcome.roi_paths if request.uses_roi else (), load_roi_artifact),):
        for path in paths:
            loader(path, 
                   source_path=request.image_path, 
                   source_axes=loaded.axes,
                   source_shape=loaded.array.shape,
                   source_channels=tuple(reader.channel_labels))
