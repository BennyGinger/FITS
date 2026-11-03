"""FITS artifact provenance and format compatibility, independent of Qt."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Any
from fits.workflows.experiments import ExperimentState
from fits.workflows.definitions.models import StepProfile
from fits.workflows.metadata._values import distribution_version
from copy import deepcopy
import json
import re
from pathlib import Path
from fits_io import FitsIO
from fits_io.metadata.models import FitsIOMeta
from fits_io.metadata.provenance import input_reference
from fits.environment import constant as cst
from fits.workflows.definitions.inputs import resolve_inputs


PARQUET_PROVENANCE_KEY = b"fits_artifact"


def read_metadata(path: Path) -> FitsIOMeta:
    """
    Read FITS provenance from a TIFF header or Parquet schema.
    """
    if path.suffix.lower() == ".parquet":
        # Image-only inspection does not need to load the Parquet engine.
        import pyarrow.parquet as pq
        data = (pq.read_schema(path).metadata or {}).get(PARQUET_PROVENANCE_KEY)
        return FitsIOMeta.from_dict(json.loads(data)) if data else FitsIOMeta()
    return FitsIO.from_path(path).reader.metadata


def compatible(metadata: FitsIOMeta) -> bool:
    """
    Check format compatibility and the presence of structured revision provenance.
    """
    version = metadata.custom_metadata.get("pipeline_meta", {}).get("version", "")
    match = re.match(r"^(\d+)\.", str(version))
    refs = metadata.fits_io.derived_from
    minimum_major = int(cst.FITS_COMPATIBLE_VERSION.split(".", 1)[0])
    return bool(match and int(match[1]) >= minimum_major and metadata.fits_io.created_at
                and isinstance(refs, list) and all(
                    isinstance(ref, dict) and isinstance(ref.get("artifact_path"), str)
                    and (ref.get("external") or ref.get("created_at")) for ref in refs))


def require_writable(path: Path) -> None:
    """
    Reject writes to older results until the run is explicitly migrated.
    """
    if path.exists() and not compatible(read_metadata(path)):
        raise ValueError("These results were created by an earlier FITS version and are read-only. "
                         "Use Manage files to migrate the run before editing or compacting.")


def produced_metadata(metadata: dict) -> dict:
    """
    Record the current FITS producer version while preserving other metadata.
    """
    result = deepcopy(metadata)
    result.setdefault("pipeline_meta", {})["version"] = distribution_version(cst.DIST_FITS)
    return result


def input_references(paths: Iterable[Path], output_directory: Path) -> list[dict]:
    """
    Record portable references to each distinct actual input revision.
    """
    return [input_reference(path, read_metadata(path), output_directory) for path in dict.fromkeys(paths)]


def revision_payload(reader: FitsIO,
                     state: ExperimentState,
                     profile: StepProfile,
                     *,
                     export_channels: str | Sequence[str],
                     ) -> FitsIOMeta:
    """
    Build output revision metadata from its actual inputs and current step settings.
    """
    paths = list(resolve_inputs(state, profile).values())
    custom = deepcopy(dict(reader.reader.metadata.custom_metadata))
    # This new output has real input provenance; it is not itself an import.
    custom.pop('migration', None)
    steps = dict(custom.get("steps", {}))
    current = state.metadata_dump.get("steps", {}).get(profile.step_name)
    if current is not None:
        steps[profile.step_name] = current
    custom["steps"] = steps
    custom["pipeline_meta"] = state.metadata_dump.get("pipeline_meta", {})
    payload = reader.build_payload(export_channels=export_channels,
                                   artifact_type=profile.output_artifact,
                                   created_by=profile.distribution,
                                   custom_metadata=produced_metadata(custom),
                                   )
    payload = replace(payload, custom_metadata=produced_metadata(custom))
    payload = payload.new_revision(input_references(paths, state.workdir))
    if profile.step_name in (cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME):
        revisions = dict(custom.get("registration_revisions", {}))
        revisions[str(profile.step_name)] = payload.fits_io.created_at
        payload = payload.with_custom_metadata({"registration_revisions": revisions})
    return payload
