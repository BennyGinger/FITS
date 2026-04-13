from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fits_io.client import FitsIO


def load_project_metadata_from_reader(reader: FitsIO) -> dict[str, Any] | None:
    """Load the project_metadata block from an already-open FITS reader."""
    raw_project_metadata = reader.fits_metadata.get("project_metadata")
    if not isinstance(raw_project_metadata, Mapping):
        return None
    return dict(raw_project_metadata)


def load_project_metadata_from_artifact(path: Path) -> dict[str, Any] | None:
    """Load the project_metadata block from a FITS artifact path."""
    if not path.exists():
        return None
    reader = FitsIO.from_path(path)
    return load_project_metadata_from_reader(reader)


def load_source_channel_indices_from_reader(reader: FitsIO) -> list[int] | None:
    """Load source channel indices from FITS metadata."""
    raw_fits_io_meta = reader.fits_metadata.get("fits_io")
    fits_io_meta = dict(raw_fits_io_meta) if isinstance(raw_fits_io_meta, Mapping) else {}
    raw_source_channel_indices = fits_io_meta.get("source_channel_indices")

    if raw_source_channel_indices is None:
        return None

    if isinstance(raw_source_channel_indices, (str, bytes)) or not isinstance(raw_source_channel_indices, Sequence):
        raise ValueError("Metadata field source_channel_indices must be a sequence of integers.")

    return [int(index) for index in raw_source_channel_indices]