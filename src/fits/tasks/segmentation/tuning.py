from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import RLock
from typing import Any, Self

import numpy as np
from numpy.typing import NDArray

from cellpose_kit.client import CellposeWrapper
from fits.sessions.image import FitsImageSession
from fits.settings.models import SegmentSettings
from fits.tasks.segmentation.preview_cache import PreviewCache, SegmentationPreview


class SegmentationTuningSession(FitsImageSession):
    """
    Load a stack and cache temporary frame-level segmentation previews.

    Preview masks are private tuning data. They are never written as FITS
    artifacts and never update an experiment state. Closing the session removes
    its complete temporary cache directory.
    """

    def __init__(self,
                 source_path: str | Path,
                 *,
                 segment_settings: SegmentSettings | Mapping[str, Any] | None = None,
                 cache_parent: str | Path | None = None,
                 ) -> None:
        super().__init__(source_path)
        self._cache = PreviewCache(self.source_path, cache_parent)
        self._lock = RLock()
        self._closed = False

        if segment_settings is None:
            segment_settings = {"channel_to_segment": [self._channel_labels[0]]}
        if not isinstance(segment_settings, SegmentSettings):
            segment_settings = SegmentSettings.model_validate(segment_settings)
        self._segment_settings = segment_settings

    @property
    def segment_settings(self) -> SegmentSettings:
        return self._segment_settings

    def set_segment_settings(self,
                             settings: SegmentSettings | Mapping[str, Any],
                             ) -> None:
        """
        Replace the validated baseline used for subsequent previews.
        """
        self._ensure_open()
        if not isinstance(settings, SegmentSettings):
            settings = SegmentSettings.model_validate(settings)
        with self._lock:
            self._segment_settings = settings

    @property
    def cache_dir(self) -> Path:
        return self._cache.directory

    @property
    def closed(self) -> bool:
        return self._closed

    def display_frame(self,
                      frame_index: int = 0,
                      channel: int | str = 0,
                      z_index: int = 0,
                      ) -> NDArray[Any]:
        """Return one selected image plane while the tuning session is open."""
        self._ensure_open()
        return super().display_frame(frame_index, channel, z_index)

    def run_preview(self,
                    frame_index: int,
                    channel: int | str = 0,
                    z_index: int = 0,
                    user_settings: Mapping[str, Any] | None = None,
                    ) -> SegmentationPreview:
        """
        Return a cached mask or run Cellpose for the selected frame.
        """
        self._ensure_open()
        channel_index = self._resolve_channel(channel)
        channel_label = self._channel_labels[channel_index]
        settings = self._preview_settings(channel_label, user_settings)
        input_labels, input_indices = self._input_channels(channel_label,
                                                           channel_index,
                                                           settings,)
        volume_preview = (bool(settings.user_settings.get("do_3D", False))
                          or float(settings.user_settings.get("stitch_threshold", 0)) > 0)
        input_array, input_axes = self._select_input(frame_index,
                                                     input_indices,
                                                     z_index,
                                                     volume_preview,)
        cache_path = self._cache.path(frame_index,
                                      None if volume_preview else z_index,
                                      input_labels,
                                      settings,)
        with self._lock:
            if cache_path.is_file():
                return self._cache.load(cache_path)

            wrapper = CellposeWrapper.from_dict(settings.model_dump())
            wrapper.setup()
            mask = wrapper.run(input_array, input_axes)
            mask_axes = wrapper.output_axis_order
            if mask_axes is None:
                raise ValueError("Cellpose preview did not provide output axes.")

            mask_array = np.asarray(mask)
            return self._cache.save(cache_path,
                                    mask=mask_array,
                                    mask_axes=mask_axes,
                                    frame_index=frame_index,
                                    input_channels=input_labels,)

    def load_cached_preview(self,
                            frame_index: int,
                            channel: int | str = 0,
                            z_index: int = 0,
                            user_settings: Mapping[str, Any] | None = None,
                            ) -> SegmentationPreview | None:
        """
        Load a matching preview if present without running Cellpose.
        """
        self._ensure_open()
        self._validate_axis_index("T", frame_index, "Frame")
        self._validate_axis_index("Z", z_index, "Z")
        channel_index = self._resolve_channel(channel)
        channel_label = self._channel_labels[channel_index]
        settings = self._preview_settings(channel_label, user_settings)
        input_labels, _ = self._input_channels(channel_label, channel_index, settings)
        volume_preview = (bool(settings.user_settings.get("do_3D", False))
                          or float(settings.user_settings.get("stitch_threshold", 0)) > 0)
        cache_path = self._cache.path(frame_index,
                                      None if volume_preview else z_index,
                                      input_labels,
                                      settings,)
        with self._lock:
            if not cache_path.is_file():
                return None
            return self._cache.load(cache_path)

    def _input_channels(self,
                        channel_label: str,
                        channel_index: int,
                        settings: SegmentSettings,
                        ) -> tuple[list[str], list[int]]:
        """
        Return selected labels and resolve each channel only once.
        """
        input_labels = [channel_label]
        input_indices = [channel_index]
        nuclear_label = settings.nuclear_channel
        if nuclear_label is not None and nuclear_label != channel_label:
            input_labels.append(nuclear_label)
            input_indices.append(self._resolve_channel(nuclear_label))
        return input_labels, input_indices

    def _select_input(self,
                      frame_index: int,
                      channel_indices: Sequence[int],
                      z_index: int,
                      volume: bool,
                      ) -> tuple[NDArray[Any], str]:
        """
        Select one timepoint, the requested channels and optionally one Z plane.
        """
        self._validate_axis_index("T", frame_index, "Frame")
        self._validate_axis_index("Z", z_index, "Z")

        indices: list[int | slice] = [slice(None)] * self._array.ndim
        removed_axes: set[str] = set()
        if "T" in self._axes:
            indices[self._axes.index("T")] = frame_index
            removed_axes.add("T")
        if "Z" in self._axes and not volume:
            indices[self._axes.index("Z")] = z_index
            removed_axes.add("Z")

        selected = self._array[tuple(indices)]
        selected_axes = "".join(axis for axis in self._axes
                                if axis not in removed_axes)
        if "C" not in selected_axes:
            if list(channel_indices) != [0]:
                raise ValueError(
                    f"Cannot select channels {list(channel_indices)} from axes {selected_axes!r}.")
            return selected, selected_axes

        channel_axis = selected_axes.index("C")
        if len(channel_indices) == 1:
            channel_selection: list[int | slice] = [slice(None)] * selected.ndim
            channel_selection[channel_axis] = channel_indices[0]
            return (selected[tuple(channel_selection)],
                    selected_axes.replace("C", "", 1),)
        return np.take(selected, channel_indices, axis=channel_axis), selected_axes

    def _preview_settings(self,
                          channel_label: str,
                          user_settings: Mapping[str, Any] | None,
                          ) -> SegmentSettings:
        """
        Merge preview controls into the validated baseline settings.
        """
        payload = self._segment_settings.model_dump()
        payload["channel_to_segment"] = [channel_label]
        payload["nuclear_channel"] = self._segment_settings.nuclear_channel
        payload["user_settings"] = {
            **self._segment_settings.user_settings,
            **dict(user_settings or {}),}
        return SegmentSettings.model_validate(payload)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cache.close()

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Segmentation tuning session is closed.")
