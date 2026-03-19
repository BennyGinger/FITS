from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from fits_io.client import FitsIO
from numpy.typing import NDArray
import numpy as np

from fits.workflows.channels.channel_merge import merge_channel_arrays
from fits.workflows.channels.metadata import src_indices_to_labels


T = TypeVar("T", bound=np.generic)


@dataclass(slots=True, frozen=True)
class ExistingMaskData:
    reader: FitsIO
    array: NDArray[Any]
    axes: str
    mask_source_indices: list[int]


@dataclass(slots=True, frozen=True)
class ProcessMaskOutput:
    array: NDArray[Any]
    axes: str
    mask_source_indices: list[int]
    channel_labels: list[str]
    structural_metadata: dict[str, Any]


def merge_step_metadata(mask_path: Path, step_name: str, step_metadata: dict[str, Any], structural_metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Merge the new processed step metadata with existing step metadata from a prior result if present, ensuring that processed source channel indices are preserved and updated in the merged metadata for accurate provenance of channels in the output artifact.
    
    Args:
        mask_path: Path to the existing mask artifact; if it exists, its metadata will be merged with the new metadata.
        step_name: Name of the step, used to locate existing step metadata in the existing artifact's metadata if present.
        step_metadata: The new step metadata to merge into the output metadata.
        structural_metadata: Metadata about source channels and processed channels to be included in the saved artifact's metadata for provenance; these keys will be promoted to the top level of the output metadata.
        
    Returns:
        Merged metadata dictionary to be included in the saved artifact's metadata, containing the merged step metadata under *step_name* and the structural metadata keys at the top level.
    """
    existing_meta_step: dict[str, Any] = {}
    if mask_path.exists():
        existing_mask_reader = FitsIO.from_path(mask_path)
        raw_existing_meta_step = existing_mask_reader.fits_metadata.get(step_name)
        existing_meta_step = dict(raw_existing_meta_step) if isinstance(raw_existing_meta_step, dict) else {}
    existing_channels = existing_meta_step.get('channels')
    merged_channels = dict(existing_channels) if isinstance(existing_channels, dict) else {}
    merged_channels.update(dict(step_metadata.get('channels', {})))
    existing_meta_step['channels'] = merged_channels
    return {**existing_meta_step, **structural_metadata}


def prepare_mask_output(image_reader: FitsIO, mask_path: Path, new_masks_array: NDArray[Any], new_axes: str, new_mask_source_indices: list[int]) -> ProcessMaskOutput:
    """
    Prepare the output array, axes, channel labels, and structural metadata for a mask artifact by merging new processing results with an existing mask artifact if present, ensuring stable channel identity and provenance of processed source channels.
    
    Args:
        image_reader: FitsIO reader for the source image, used to resolve source channel identity and labels for the output mask channels.
        mask_path: Path to the existing mask artifact; if it exists, its array and metadata will be merged with the new results.
        new_masks_array: The newly produced produced mask array to merge into the output.
        new_axes: Axes string for the new produced mask array.
        new_mask_source_indices: List of source channel indices corresponding to the new masks; used to maintain stable channel identity in the output and record processed channels in the metadata.
    
    Returns:
        ProcessMaskOutput containing the merged mask array, its axes string, the list of source channel indices, the corresponding channel labels for the output mask channels, and structural metadata about source channels and processed channels to be included in the saved artifact's metadata for provenance.
    """
    existing = _load_existing_masks(mask_path)
    merged_array, merged_axes, merged_mask_source_indices = _merge_or_initialize_masks(existing, new_masks_array, new_axes, new_mask_source_indices, image_reader.axes[0])
    merged_channel_labels = src_indices_to_labels(image_reader, merged_mask_source_indices)
    _validate_mask_output(merged_array, merged_axes, merged_channel_labels)
    # fits_io drops 'C' from ImageJ axes when n_channels==1; squeeze the singleton C axis to match.
    c_ax = merged_axes.find('C')
    if c_ax != -1 and merged_array.shape[c_ax] == 1:
        merged_array = merged_array.squeeze(c_ax)
        merged_axes = merged_axes.replace('C', '')
    structural_metadata = _build_mask_structural_metadata(merged_mask_source_indices)
    return ProcessMaskOutput(array=merged_array, axes=merged_axes, mask_source_indices=merged_mask_source_indices, channel_labels=merged_channel_labels, structural_metadata=structural_metadata)


# -------- Internal Helpers --------

def _load_existing_masks(mask_path: Path) -> ExistingMaskData | None:
    if not mask_path.exists():
        return None
    mask_reader = FitsIO.from_path(mask_path)
    existing_array = mask_reader.get_array()
    if isinstance(existing_array, list):
        raise ValueError(f"Existing mask artifact {mask_path} is multi-series; mask merge only supports single-series arrays.")
    existing_axes = mask_reader.axes[0]
    raw_mask_source = mask_reader.fits_metadata.get("mask_source_channel_indices")
    if raw_mask_source is None:
        raise ValueError(f"Existing mask artifact {mask_path} is missing mask_source_channel_indices; cannot safely merge channels.")
    existing_mask_source_indices = [int(index) for index in raw_mask_source]
    return ExistingMaskData(reader=mask_reader, array=existing_array, axes=existing_axes, mask_source_indices=existing_mask_source_indices)


def _merge_or_initialize_masks(existing: ExistingMaskData | None, new_masks_array: NDArray[T], new_axes: str, new_mask_source_indices: list[int], reference_axes: str) -> tuple[NDArray[T], str, list[int]]:
    if existing is None:
        return merge_channel_arrays(None, None, None, new_masks_array, new_axes, new_mask_source_indices, reference_axes)
    return merge_channel_arrays(existing.array, existing.axes, existing.mask_source_indices, new_masks_array, new_axes, new_mask_source_indices, reference_axes)


def _build_mask_structural_metadata(mask_source_channel_indices: list[int]) -> dict[str, Any]:
    return {"mask_source_channel_indices": list(mask_source_channel_indices)}


def _validate_mask_output(array: Any, axes: str, channel_labels: list[str]) -> None:
    if len(axes) != array.ndim:
        raise ValueError(f"Merged mask output is inconsistent: axes={axes!r}, shape={array.shape}")
    c_ax = axes.find('C')
    if c_ax != -1 and array.shape[c_ax] != len(channel_labels):
        raise ValueError(f"Merged mask labels do not match channel axis: axes={axes!r}, shape={array.shape}, labels={channel_labels}")

