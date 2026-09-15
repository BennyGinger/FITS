"""Run-level workflow provenance metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from fits.environment.constant import DIST_FITS
from fits.workflows.metadata._values import distribution_version, utc_now


@dataclass(slots=True, frozen=True)
class RunMetadata:
    """
    Record who created a workflow run, with its version and timestamp.
    """
    created_by: str = DIST_FITS
    user_name: str | None = None
    version: str | None = None
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.version is None:
            object.__setattr__(self, "version", distribution_version(self.created_by))
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", utc_now())

    def with_user(self, user_name: str) -> RunMetadata:
        """
        Return updated run metadata for the given user and current time.
        """
        return replace(self,
                        user_name=user_name,
                        version=distribution_version(self.created_by),
                        timestamp=utc_now(),)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunMetadata:
        """
        Create run metadata from its serialized representation.
        """
        return cls(created_by=data.get("created_by", DIST_FITS),
                    user_name=data.get("user_name"),
                    version=data.get("version"),
                    timestamp=data.get("timestamp"),)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize the run metadata.
        """
        return {"user_name": self.user_name,
                "created_by": self.created_by,
                "version": self.version,
                "timestamp": self.timestamp,}
