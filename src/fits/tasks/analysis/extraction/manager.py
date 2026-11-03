from dataclasses import dataclass
import logging
from pathlib import Path

from fits_io import FitsIO
import numpy as np
from bioimagequant import ExtractData

from fits.environment import constant as cst
from fits.tasks.analysis.manager import AnalysisManager, project_z
from fits.workflows.experiments import ExperimentState


logger = logging.getLogger(__name__)


def resolve_extraction_labels(state: ExperimentState) -> tuple[str, Path]:
    """
    Select the active tracking result, otherwise segmentation, for analysis/preview.
    """
    for kind in (cst.ARTI_TRACK, cst.ARTI_SEG):
        path = state.artifact(kind)
        if path is not None and path.is_file():
            return kind, path
    raise ValueError("Extraction requires a tracking or segmentation artifact.")


@dataclass
class ExtractionManager(AnalysisManager):

    def _resolve_labels(self) -> tuple[str, Path]:
        """
        Resolve the label artifact to use for extraction, based on their priority: 
            - tracking > segmentation. 
        
        Returns a tuple of (label_name, label_path).
        """
        
        return resolve_extraction_labels(self.state)


    def prepare_quantification(self) -> ExtractData:
        """
        Load the image and label artifacts from the experiment state and prepare an ExtractData instance for quantification.
        """
        label_name, label_path = self._resolve_labels()

        image_reader = self.image_reader
        label_reader = FitsIO.from_path(label_path)

        image = image_reader.get_array()
        labels = label_reader.get_array()
        image_array, image_axes = project_z(
            np.asarray(image.array), image.axes, mask=False)
        label_array, label_axes = project_z(
            np.asarray(labels.array), labels.axes, mask=False)
        if "Z" in image.axes or "Z" in labels.axes:
            logger.info("Extraction is two-dimensional; automatically max-projecting Z for %s.",
                        self.state.experiment_id,)

        pixel_size = self.isotropic_pixel_size_um(spatial_axes=label_axes.replace("T", "").replace("C", ""),)
        extractor = ExtractData(interval=image_reader.interval,
                                pixel_size=pixel_size,)

        extractor.add_intensity(image_array,
                                image_axes,
                                channel_labels=image_reader.channel_labels,)

        extractor.add_labels(label_array,
                            label_axes,
                            name=label_name,
                            channel_labels=label_reader.channel_labels,)

        for reference_path in self.reference_paths():
            reference_reader = FitsIO.from_path(reference_path)
            reference = reference_reader.get_array()
            reference_array, reference_axes = project_z(
                np.asarray(reference.array), reference.axes, mask=True)
            reference_name = reference_path.stem.removeprefix("fits_ref_")
            extractor.add_ref(reference_array,
                                reference_axes,
                                name=reference_name,
                                channel_labels=reference_reader.channel_labels,)
        return extractor
