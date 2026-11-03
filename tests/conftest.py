"""Shared test fixtures and utilities for FITS tests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


# ============================================================
# Common test utilities
# ============================================================

def _touch_file(p: Path) -> Path:
    """Create a file at the given path, creating parent directories as needed.
    
    Args:
        p: Path where the file should be created.
        
    Returns:
        The same path that was passed in.
    """
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")  # content irrelevant for tests
    return p


# ============================================================
# Mock/Stub classes
# ============================================================

class DummyFitsIO:
    """Mock FitsIO object for testing without actual file I/O."""
    
    def __init__(self, metadata: dict[str, Any] | None = None):
        self.fits_metadata = metadata or {}


@dataclass
class DummyCtx:
    """Mock ExecutionContext for testing."""
    user_name: str


# ============================================================
# Pytest fixtures
# ============================================================

@pytest.fixture
def touch():
    """Fixture that provides the touch utility function."""
    return _touch_file


@pytest.fixture
def dummy_fits_io():
    """Factory fixture for creating DummyFitsIO instances."""
    def _make(metadata: dict[str, Any] | None = None) -> DummyFitsIO:
        return DummyFitsIO(metadata)
    return _make


@pytest.fixture
def dummy_ctx():
    """Factory fixture for creating DummyCtx instances."""
    def _make(user_name: str = "test_user") -> DummyCtx:
        return DummyCtx(user_name=user_name)
    return _make


@pytest.fixture
def DummyFitsIO_class():
    """Fixture that provides access to the DummyFitsIO class."""
    return DummyFitsIO


@pytest.fixture
def DummyCtx_class():
    """Fixture that provides access to the DummyCtx class."""
    return DummyCtx


@pytest.fixture
def current_format_tiffs(monkeypatch):
    """Write fixtures with the FITS 4 metadata contract, retaining lazy test reads."""
    import json
    import tifffile
    from fits_io.metadata.models import FitsIOMeta
    from fits_io.metadata.codec import FITS_TAG
    original = tifffile.imwrite
    def write(path, *args, **kwargs):
        kind = 'tracking' if 'track' in Path(path).name else 'image_raw'
        payload = FitsIOMeta().with_fitsio(artifact_type=kind).with_custom_metadata(
            {'pipeline_meta': {'version': '4.0.0'}}).new_revision()
        tags = list(kwargs.get('extratags') or [])
        if not any(tag[0] == FITS_TAG for tag in tags):
            data = json.dumps(payload.dump()).encode()
            kwargs['extratags'] = [*tags, (FITS_TAG, 7, len(data), data, False)]
        return original(path, *args, **kwargs)
    monkeypatch.setattr(tifffile, 'imwrite', write)
