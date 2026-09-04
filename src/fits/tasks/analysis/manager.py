from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from fits_io import FitsIO
import numpy as np

from fits.environment.constant import (
    ARTI_IMG,
    FITS_REFERENCE_TEMPLATE,
    FITS_ROI_TEMPLATE,
)
from fits.environment.state import ExperimentState


logger = logging.getLogger(__name__)


@dataclass
class AnalysisManager:
    """Shared FITS artifact access for experiment-level analyses."""

    state: ExperimentState
    _reader: FitsIO | None = field(init=False, default=None, repr=False)

    @property
    def image_path(self) -> Path:
        path = self.state.artifact(ARTI_IMG)
        if path is None or not path.is_file():
            raise ValueError("Analysis requires an image artifact.")
        return path

    @property
    def image_reader(self) -> FitsIO:
        if self._reader is None:
            self._reader = FitsIO.from_path(self.image_path)
        return self._reader

    def reference_paths(self) -> tuple[Path, ...]:
        return tuple(sorted(self.state.workdir.glob(
            FITS_REFERENCE_TEMPLATE.format(label="*"))))

    def roi_paths(self) -> tuple[Path, ...]:
        return tuple(sorted(self.state.workdir.glob(
            FITS_ROI_TEMPLATE.format(label="*"))))

    def isotropic_pixel_size_um(self, *, spatial_axes: str = "YX") -> float | None:
        """Return isotropic XY calibration, or ``None`` when unavailable."""
        resolution = self.image_reader.resolution
        if resolution is None:
            return None
        if "Z" in spatial_axes:
            logger.warning(
                "Physical distances are unavailable for unprojected Z data.")
            return None

        x_size, y_size = resolution
        if not np.isclose(x_size, y_size):
            logger.warning(
                "Physical distances are unavailable for anisotropic XY pixels.")
            return None
        return float(x_size)
