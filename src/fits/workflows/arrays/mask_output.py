from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from fits_io.client import FitsIO
from numpy.typing import NDArray
import numpy as np

from fits.workflows.arrays.channel_merge import merge_channel_arrays
from fits.workflows.metadata.channel_identity import src_indices_to_labels
from fits.workflows.arrays.validations import validate_mask_output
from fits.workflows.metadata.loading import load_project_metadata_from_reader


T = TypeVar("T", bound=np.generic)


@dataclass(slots=True, frozen=True)
class ExistingMaskData:
    reader: FitsIO
    array: NDArray[Any]
    axes: str
    mask_source_indices: list[int]
    project_metadata: dict[str, Any] | None


@dataclass(slots=True, frozen=True)
class ProcessMaskOutput:
    array: NDArray[Any]
    axes: str
    mask_source_indices: list[int]
    channel_labels: list[str]
    existing_project_metadata: dict[str, Any] | None


def prepare_mask_output(image_reader: FitsIO, mask_path: Path, new_masks_array: NDArray[Any], new_axes: str, new_mask_source_indices: list[int], step_name: str, overwrite: bool = False) -> ProcessMaskOutput:
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
    existing = None if overwrite else _load_existing_masks(mask_path, step_name)
    merged_array, merged_axes, merged_mask_source_indices = _merge_or_initialize_masks(existing, new_masks_array, new_axes, new_mask_source_indices, image_reader.axes[0])
    merged_channel_labels = src_indices_to_labels(image_reader, merged_mask_source_indices)
    validate_mask_output(merged_array, merged_axes, merged_channel_labels)
    # fits_io drops 'C' from ImageJ axes when n_channels==1; squeeze the singleton C axis to match.
    c_ax = merged_axes.find('C')
    if c_ax != -1 and merged_array.shape[c_ax] == 1:
        merged_array = merged_array.squeeze(c_ax)
        merged_axes = merged_axes.replace('C', '')
    existing_project_metadata = None if existing is None else existing.project_metadata
    return ProcessMaskOutput(
        array=merged_array,
        axes=merged_axes,
        mask_source_indices=merged_mask_source_indices,
        channel_labels=merged_channel_labels,
        existing_project_metadata=existing_project_metadata,
    )


# -------- Internal Helpers --------

def _load_existing_masks(mask_path: Path, step_name: str) -> ExistingMaskData | None:
    if not mask_path.exists():
        return None
    mask_reader = FitsIO.from_path(mask_path)
    existing_array = mask_reader.get_array()
    if isinstance(existing_array, list):
        raise ValueError(f"Existing mask artifact {mask_path} is multi-series; mask merge only supports single-series arrays.")
    existing_axes = mask_reader.axes[0]
    project_metadata = load_project_metadata_from_reader(mask_reader)
    raw_step_metadata = project_metadata.get("steps", {}).get(step_name) if isinstance(project_metadata, Mapping) else None
    raw_mask_source = raw_step_metadata.get("mask_source_channel_indices") if isinstance(raw_step_metadata, Mapping) else None
    if raw_mask_source is None:
        raise ValueError(
            f"Existing mask artifact {mask_path} is missing required metadata field "
            f"project_metadata.steps.{step_name}.mask_source_channel_indices; cannot safely merge channels."
        )
    existing_mask_source_indices = [int(index) for index in raw_mask_source]
    return ExistingMaskData(
        reader=mask_reader,
        array=existing_array,
        axes=existing_axes,
        mask_source_indices=existing_mask_source_indices,
        project_metadata=project_metadata,
    )


def _merge_or_initialize_masks(existing: ExistingMaskData | None, new_masks_array: NDArray[T], new_axes: str, new_mask_source_indices: list[int], reference_axes: str) -> tuple[NDArray[T], str, list[int]]:
    if existing is None:
        return merge_channel_arrays(None, None, None, new_masks_array, new_axes, new_mask_source_indices, reference_axes)
    return merge_channel_arrays(existing.array, existing.axes, existing.mask_source_indices, new_masks_array, new_axes, new_mask_source_indices, reference_axes)

