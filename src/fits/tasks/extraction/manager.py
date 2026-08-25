from dataclasses import dataclass
from pathlib import Path

from fits_io import FitsIO
from labelquant import ExtractData

from fits.environment.constant import ARTI_IMG, ARTI_SEG, ARTI_TRACK
from fits.environment.state import ExperimentState

@dataclass
class ExtractionManager:
    state: ExperimentState

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

        return extractor
