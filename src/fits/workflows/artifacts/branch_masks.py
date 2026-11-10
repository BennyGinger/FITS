"""REF/ROI geometry dependencies, independent of image-intensity revisions."""

from __future__ import annotations

from typing import Any
from scope_io.metadata.models import ImageMetadata
from fits.workflows.experiments import ExperimentState
from fits.workflows.metadata._values import utc_now
from dataclasses import replace
from pathlib import Path
from fits.workflows.artifacts.provenance import compatible, produced_metadata, read_metadata
from fits.environment import constant as cst
from scope_io.writers.metadata_update import rewrite_metadata


def is_branch(path: Path) -> bool:
    """
    Identify REF/ROI masks through their FITS-owned filename conventions.
    """
    return path.match(cst.FITS_REFERENCE_TEMPLATE.format(label="*")) or path.match(cst.FITS_ROI_TEMPLATE.format(label="*"))


def geometry(metadata: ImageMetadata) -> Any:
    """
    Return registration geometry independently of intensity-only revisions.
    """
    dependency = metadata.custom_metadata.get('geometry_dependency')
    if dependency is not None:
        return dependency
    revisions = metadata.custom_metadata.get("registration_revisions")
    if revisions is not None:
        return revisions
    steps = metadata.custom_metadata.get("steps", {})
    # Earlier branch files carry the original per-step registration metadata.
    # Later intensity-only writes copy it unchanged. A registration rerun gets
    # a fresh revision even if its settings happen to be identical.
    return [{"step": name, "metadata": step}
            for name, step in steps.items()
            if name in (cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME)]


def refresh_branch(path: Path, image: Path, *, accept_geometry: bool = False) -> None:
    """
    Refresh branch.
    """
    old = read_metadata(path)
    source = read_metadata(image)
    changed = geometry(old) != geometry(source)
    if changed and not accept_geometry:
        raise ValueError(f"Registration changed: review {path.name} against the current image before reusing its geometry.")
    if compatible(old) and old.custom_metadata.get("geometry_dependency") == geometry(source):
        return
    # Keep existing revisions; upgrading an older branch's metadata is an explicit
    # exception authorized for retained manual drawings, never a pixel rebuild.
    revision = old if old.artifact.created_at else old.new_revision()
    payload = revision.with_custom_metadata(produced_metadata(dict(old.custom_metadata)))
    payload = payload.with_custom_metadata({"geometry_dependency": geometry(source)})
    if changed:
        payload = payload.with_custom_metadata({'geometry_review': {
            'accepted_at': utc_now(), 'previous_geometry': geometry(old),
            'accepted_geometry': geometry(source)}})
    payload = replace(payload, artifact=replace(payload.artifact, derived_from=[]))
    rewrite_metadata(path, payload)


def refresh_branches(state: ExperimentState) -> None:
    """
    Refresh branches.
    """
    image = state.artifact(cst.ARTI_IMG)
    if image is None or not image.is_file():
        return
    for pattern in (cst.FITS_REFERENCE_TEMPLATE, cst.FITS_ROI_TEMPLATE):
        for path in state.workdir.glob(pattern.format(label="*")):
            refresh_branch(path, image)
