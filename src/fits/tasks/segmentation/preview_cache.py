from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any

import numpy as np
from numpy.typing import NDArray

from fits.settings.models import SegmentSettings


@dataclass(frozen=True, slots=True)
class SegmentationPreview:
    """
    One frame-level Cellpose result produced for interactive tuning.
    """

    mask: NDArray[Any]
    mask_axes: str
    frame_index: int
    input_channels: tuple[str, ...]
    cache_path: Path
    from_cache: bool


class PreviewCache:
    """
    Own temporary preview files and their NPZ serialization.
    """

    def __init__(self,
                 source_path: Path,
                 cache_parent: str | Path | None = None,
                 ) -> None:
        cache_root = (Path(cache_parent).expanduser().resolve()
                      if cache_parent is not None
                      else None)
        if cache_root is not None:
            cache_root.mkdir(parents=True, exist_ok=True)

        self.source_path = source_path
        self._temporary_directory = TemporaryDirectory(
            prefix="fits_segmentation_tuning_",
            dir=cache_root,)
        self.directory = Path(self._temporary_directory.name)

    def path(self,
             frame_index: int,
             z_index: int | None,
             input_labels: Sequence[str],
             settings: SegmentSettings,
             ) -> Path:
        stat = self.source_path.stat()
        payload = {"source": str(self.source_path),
                   "source_size": stat.st_size,
                   "source_mtime_ns": stat.st_mtime_ns,
                   "frame_index": frame_index,
                   "z_index": z_index,
                   "input_labels": list(input_labels),
                   "settings": settings.model_dump(exclude={"model"}),}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:12]
        labels = "-".join(self._safe_name(label) for label in input_labels)
        return self.directory / f"frame_{frame_index:06d}__{labels}__{digest}.npz"

    def save(self,
             cache_path: Path,
             *,
             mask: NDArray[Any],
             mask_axes: str,
             frame_index: int,
             input_channels: Sequence[str],
             ) -> SegmentationPreview:
        with NamedTemporaryFile(dir=cache_path.parent,
                                prefix=f".{cache_path.stem}_",
                                suffix=".npz",
                                delete=False,) as temporary:
            temporary_path = Path(temporary.name)
            np.savez_compressed(temporary,
                                mask=mask,
                                mask_axes=np.asarray(mask_axes),
                                frame_index=np.asarray(frame_index),
                                input_channels=np.asarray(list(input_channels)),)
        os.replace(temporary_path, cache_path)
        return SegmentationPreview(mask=mask,
                                   mask_axes=mask_axes,
                                   frame_index=frame_index,
                                   input_channels=tuple(input_channels),
                                   cache_path=cache_path,
                                   from_cache=False,)

    @staticmethod
    def load(cache_path: Path) -> SegmentationPreview:
        with np.load(cache_path, allow_pickle=False) as cached:
            mask = np.asarray(cached["mask"])
            mask_axes = str(cached["mask_axes"].item())
            frame_index = int(cached["frame_index"].item())
            input_channels = tuple(str(value) for value in cached["input_channels"])
        return SegmentationPreview(mask=mask,
                                   mask_axes=mask_axes,
                                   frame_index=frame_index,
                                   input_channels=input_channels,
                                   cache_path=cache_path,
                                   from_cache=True,)

    def close(self) -> None:
        self._temporary_directory.cleanup()

    @staticmethod
    def _safe_name(value: str) -> str:
        safe = "".join(
            char if char.isalnum() or char in "-_" else "_" for char in value)
        return safe.strip("_") or "channel"
