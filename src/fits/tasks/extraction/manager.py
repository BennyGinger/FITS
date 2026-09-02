from dataclasses import dataclass, field
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from fits_io import FitsIO
from labelquant import ExtractData

from fits.environment.constant import (
    ARTI_IMG,
    ARTI_SEG,
    ARTI_TRACK,
    FITS_REFERENCE_TEMPLATE,
)
from fits.environment.state import ExperimentState


logger = logging.getLogger(__name__)


@dataclass
class ExtractionManager:
    state: ExperimentState
    _pixel_size_um: float | None = field(init=False, default=None)

    def _resolve_labels(self) -> tuple[str, Path]:
        """
        Resolve the label artifact to use for extraction, based on their priority: 
            - tracking > segmentation. 
        
        Returns a tuple of (label_name, label_path).
        """
        
        tracking = self.state.artifact(ARTI_TRACK)

        if tracking is not None and tracking.exists():
            return ARTI_TRACK, tracking

        segmentation = self.state.artifact(ARTI_SEG)

        if segmentation is not None and segmentation.exists():
            return ARTI_SEG, segmentation

        raise ValueError("Extraction requires a tracking or segmentation artifact.")


    def prepare_quantification(self) -> ExtractData:
        """
        Load the image and label artifacts from the experiment state and prepare an ExtractData instance for quantification.
        """
        image_path = self.state.artifact(ARTI_IMG)

        if image_path is None or not image_path.exists():
            raise ValueError("Extraction requires an image artifact.")

        label_name, label_path = self._resolve_labels()

        image_reader = FitsIO.from_path(image_path)
        label_reader = FitsIO.from_path(label_path)

        image = image_reader.get_array()
        labels = label_reader.get_array()

        self._pixel_size_um = _isotropic_pixel_size(
            image_reader.resolution,
            spatial_axes=labels.axes.replace("T", "").replace("C", ""),)

        extractor = ExtractData(interval=image_reader.interval)

        extractor.add_array(
            "intensity",
            image.array,
            image.axes,
            channel_labels=image_reader.channel_labels,
        )

        extractor.add_array(
            "object_labels",
            labels.array,
            labels.axes,
            name=label_name,
            channel_labels=label_reader.channel_labels,
        )

        for reference_path in sorted(self.state.workdir.glob(
                FITS_REFERENCE_TEMPLATE.format(label="*"))):
            reference_reader = FitsIO.from_path(reference_path)
            reference = reference_reader.get_array()
            reference_name = reference_path.stem.removeprefix("fits_ref_")
            extractor.add_array(
                "reference",
                reference.array,
                reference.axes,
                name=reference_name,
                channel_labels=reference_reader.channel_labels,)

        return extractor

    def add_physical_distances(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """Add micrometre distances when isotropic XY calibration is available."""
        if "dist_pixel" not in dataframe:
            return dataframe

        result = dataframe.copy()
        if self._pixel_size_um is None:
            result["dist_um"] = np.nan
        else:
            result["dist_um"] = result["dist_pixel"] * self._pixel_size_um
        return result


def _isotropic_pixel_size(resolution: tuple[float, float] | None,
                          *,
                          spatial_axes: str,
                          ) -> float | None:
    if resolution is None:
        return None
    if "Z" in spatial_axes:
        logger.warning(
            "Reference distances include Z but no Z calibration is available; dist_um will be missing.")
        return None

    x_size, y_size = resolution
    if not np.isclose(x_size, y_size):
        logger.warning(
            "Reference distances use anisotropic XY pixels; dist_um will be missing.")
        return None
    return float(x_size)
