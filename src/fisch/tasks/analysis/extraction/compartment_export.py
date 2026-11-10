"""Optional FIScH compartment-mask exports, derived from active source labels."""

from dataclasses import asdict
from pathlib import Path

import numpy as np
from bioimagequant import CompartmentSettings, compartment_masks
from bioimagequant.core.arrays import ArrayData
from scope_io import ScopeIO

from fisch.environment import constant as cst
from fisch.tasks.analysis.extraction.manager import resolve_extraction_labels
from fisch.tasks.analysis.manager import project_z
from fisch.workflows.experiments import ExperimentState
from fisch.workflows.definitions.models import StepProfile


def compartment_export_paths(source: Path) -> tuple[Path, Path]:
    """
    Return membrane and cytoplasm paths without changing the source filename.
    """
    return source.with_name(f"{source.stem}_mb.tif"), source.with_name(f"{source.stem}_cyto.tif")


def export_compartments(state: ExperimentState, settings: CompartmentSettings, *, profile: StepProfile | None = None) -> tuple[Path, Path]:
    """
    Write source-shaped mask channels through the ordinary FIScH TIFF protocol.
    """
    _, source = resolve_extraction_labels(state, profile)
    reader = ScopeIO.from_path(source)
    raw = reader.get_array()
    array, axes = project_z(np.asarray(raw.array), raw.axes, mask=False)
    data = ArrayData(array, axes, channel_labels=reader.channel_labels)
    outputs = {name: np.zeros_like(data.array) for name in ("mb", "cyto")}
    for frame in range(data.frame_count):
        for channel in range(data.channel_count):
            selection = tuple(frame if axis == "T" else channel if axis == "C" else slice(None)
                              for axis in data.axes)
            masks = compartment_masks(data.array[selection], settings)
            for name, output in outputs.items():
                output[selection] = masks[name]
    paths = compartment_export_paths(source)
    for (name, output), path in zip(outputs.items(), paths, strict=True):
        if "C" in axes:
            output = np.moveaxis(output, -1, axes.index("C"))
        reader.save_array(output,
                          output_path=path,
                          artifact_kind=f"compartment_{name}",
                          created_by=cst.DIST_EXTRACT,
                          z_projection="max" if "Z" in raw.axes else None,
                          custom_metadata={"compartments": {"name": name, **asdict(settings)}},
                          )
    return paths
