from dataclasses import dataclass
import logging
from pathlib import Path

from fits_io import FitsIO
from bioimagequant import ExtractData

from fits.environment.constant import (
    ARTI_SEG,
    ARTI_TRACK,
)
from fits.tasks.analysis.manager import AnalysisManager


logger = logging.getLogger(__name__)


@dataclass
class ExtractionManager(AnalysisManager):

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
        label_name, label_path = self._resolve_labels()

        image_reader = self.image_reader
        label_reader = FitsIO.from_path(label_path)

        image = image_reader.get_array()
        labels = label_reader.get_array()

        pixel_size = self.isotropic_pixel_size_um(
            spatial_axes=labels.axes.replace("T", "").replace("C", ""),)
        extractor = ExtractData(
            interval=image_reader.interval,
            pixel_size=pixel_size,)

        extractor.add_intensity(
            image.array,
            image.axes,
            channel_labels=image_reader.channel_labels,
        )

        extractor.add_labels(
            labels.array,
            labels.axes,
            name=label_name,
            channel_labels=label_reader.channel_labels,
        )

        for reference_path in self.reference_paths():
            reference_reader = FitsIO.from_path(reference_path)
            reference = reference_reader.get_array()
            reference_name = reference_path.stem.removeprefix("fits_ref_")
            extractor.add_ref(
                reference.array,
                reference.axes,
                name=reference_name,
                channel_labels=reference_reader.channel_labels,)

        return extractor
