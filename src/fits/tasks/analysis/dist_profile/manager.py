from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import numpy as np
from numpy.typing import NDArray
import pandas as pd
from bioimagequant import DistanceProfiler

from fits.settings.models import DistanceProfileSettings
from fits.tasks.analysis.manager import AnalysisManager
from fits.tasks.reference_mask.artifact import load_reference_artifact
from fits.tasks.roi_mask.artifact import load_roi_artifact


logger = logging.getLogger(__name__)


@dataclass
class DistanceProfileManager(AnalysisManager):
    """Load FITS artifacts and delegate profiling to ``bioimagequant``."""

    settings: DistanceProfileSettings

    def calculate(self) -> pd.DataFrame:
        reader = self.image_reader
        loaded = reader.get_array()
        source = np.asarray(loaded.array)
        source_axes = loaded.axes
        source_channels = tuple(reader.channel_labels)
        image, image_axes = _project_z(source, source_axes, mask=False)
        z_projection = "max" if "Z" in source_axes else None
        if z_projection is not None:
            logger.info(
                "Distance profile is two-dimensional; automatically max-projecting Z for %s.",
                self.state.experiment_id,)

        profiler = DistanceProfiler(
            interval=reader.interval,
            pixel_size=self.isotropic_pixel_size_um(spatial_axes="YX"),)
        profiler.add_intensity(
            image,
            image_axes,
            channel_labels=source_channels,)

        for path in self.reference_paths():
            reference, name, channels = load_reference_artifact(
                path,
                source_path=self.image_path,
                source_axes=source_axes,
                source_shape=source.shape,
                source_channels=source_channels,)
            compact, axes = _compact_mask_channels(
                reference, source_axes, source_channels, channels)
            projected, axes = _project_z(compact != 0, axes, mask=True)
            profiler.add_ref(
                projected, axes, name=name, channel_labels=channels)

        for path in self.roi_paths():
            roi, name, channels = load_roi_artifact(
                path,
                source_path=self.image_path,
                source_axes=source_axes,
                source_shape=source.shape,
                source_channels=source_channels,)
            compact, axes = _compact_mask_channels(
                roi, source_axes, source_channels, channels)
            projected, axes = _project_z(compact >= 3, axes, mask=True)
            profiler.add_roi(
                projected, axes, name=name, channel_labels=channels)

        dataframe = profiler.calculate(
            bin_width=self.settings.bin_width,
            maximum_bins=self.settings.maximum_bins,)
        dataframe.insert(0, "experiment_id", self.state.experiment_id)
        roi_channel_position = dataframe.columns.get_loc("roi_channel")
        if not isinstance(roi_channel_position, (int, np.integer)):
            raise ValueError("Distance profile output must have one roi_channel column")
        insert_at = int(roi_channel_position) + 1
        dataframe.insert(insert_at, "z_projection", z_projection)
        return dataframe


def _compact_mask_channels(mask: NDArray[Any],
                           axes: str,
                           source_channels: tuple[str, ...],
                           mask_channels: tuple[str, ...],
                           ) -> tuple[NDArray[Any], str]:
    """Remove empty source-channel slots introduced while loading an artifact."""
    if "C" not in axes:
        return mask, axes
    indices = [source_channels.index(channel) for channel in mask_channels]
    channel_axis = axes.index("C")
    if len(indices) == 1:
        return np.take(mask, indices[0], axis=channel_axis), axes.replace("C", "")
    return np.take(mask, indices, axis=channel_axis), axes


def _project_z(array: NDArray[Any],
               axes: str,
               *,
               mask: bool,
               ) -> tuple[NDArray[Any], str]:
    """Apply FITS' automatic 2D policy while preserving all other axes."""
    if "Z" not in axes:
        return array, axes
    z_axis = axes.index("Z")
    projected = (np.any(array, axis=z_axis)
                 if mask else np.max(array, axis=z_axis))
    return projected, axes.replace("Z", "")
