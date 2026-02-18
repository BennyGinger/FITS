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
