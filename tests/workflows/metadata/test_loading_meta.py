from __future__ import annotations

from pathlib import Path
from typing import cast

from fits_io.client import FitsIO

from fits.workflows.metadata.loading import load_project_metadata_from_artifact, load_project_metadata_from_reader


class DummyReader:
    def __init__(self, fits_metadata: dict[str, object] | None = None) -> None:
        self.fits_metadata = fits_metadata or {}


def test_load_project_metadata_from_reader_returns_copy() -> None:
    reader = DummyReader({"project_metadata": {"steps": {"segment": {"k": 1}}}})

    out = load_project_metadata_from_reader(cast(FitsIO, reader))

    assert out == {"steps": {"segment": {"k": 1}}}
    assert out is not reader.fits_metadata["project_metadata"]


def test_load_project_metadata_from_reader_returns_none_when_missing() -> None:
    reader = DummyReader({})

    assert load_project_metadata_from_reader(cast(FitsIO, reader)) is None


def test_load_project_metadata_from_artifact_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert load_project_metadata_from_artifact(tmp_path / "missing.tif") is None


def test_load_project_metadata_from_artifact_reads_with_fitsio(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "fits_array.tif"
    path.write_bytes(b"")
    dummy_reader = DummyReader({"project_metadata": {"pipeline": {"distribution": "fits"}}})

    monkeypatch.setattr("fits.workflows.metadata.loading.FitsIO.from_path", lambda p: dummy_reader)

    out = load_project_metadata_from_artifact(path)

    assert out == {"pipeline": {"distribution": "fits"}}
