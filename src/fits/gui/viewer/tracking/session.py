"""Artifact loading and navigation for the tracking viewer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from fits_io import FitsIO

from fits.environment.constant import DIST_FITS, FITS_ARRAY_NAME, FITS_MASK_TRACK
from fits.gui.viewer.tracking.rendering import render_tracking_display
from fits.gui.viewer.tracking.trajectories import calculate_track_centroids
from fits.interaction import FitsImageSession


class TrackingViewerSession:
    """

    Load and navigate a tracked-label artifact and optional sibling image.

    """

    def __init__(self, tracking_path: str | Path) -> None:
        self.source_path = Path(tracking_path).expanduser().resolve()
        if not self.source_path.is_file() or self.source_path.name != FITS_MASK_TRACK:
            raise ValueError(f"Select a tracking artifact named {FITS_MASK_TRACK!r}.")

        self._reader = FitsIO.from_path(self.source_path)
        result = self._reader.get_array()
        self._tracks = np.asarray(result.array)
        self._axes = result.axes
        self._channel_labels = tuple(self._reader.channel_labels)
        self._centroid_cache: dict[tuple[int, int], dict[int, NDArray[np.float64]]] = {}
        if len(self._axes) != self._tracks.ndim or not {"Y", "X"}.issubset(self._axes):
            raise ValueError(f"Tracking axes {self._axes!r} do not match a YX label movie "
                             f"with shape {self._tracks.shape}.")

        channel_count = self._axis_size("C")
        if not self._channel_labels:
            self._channel_labels = tuple(f"Channel {index + 1}" for index in range(channel_count))

        if len(self._channel_labels) != channel_count:
            raise ValueError(f"Tracking has {channel_count} channels but "
                            f"{len(self._channel_labels)} channel labels.")
        image_path = self.source_path.with_name(FITS_ARRAY_NAME)
        self.image_session = (FitsImageSession(image_path) if image_path.is_file() else None)

    @property
    def axes(self) -> str:
        return self._axes

    @property
    def shape(self) -> tuple[int, ...]:
        return self._tracks.shape

    @property
    def channel_labels(self) -> tuple[str, ...]:
        """

        Return channels available for optional raw-image display.

        """
        if self.image_session is not None:
            return self.image_session.channel_labels
        return ("No raw image",)

    @property
    def track_channel_labels(self) -> tuple[str, ...]:
        return self._channel_labels

    @property
    def frame_count(self) -> int:
        return self._axis_size("T")

    @property
    def plane_count(self) -> int:
        return self._axis_size("Z")

    def display_frame(self, frame_index: int = 0, channel: int | str = 0, z_index: int = 0,) -> NDArray[Any]:
        """

        Return a raw-image plane or a blank plane shaped like the labels.

        """
        if self.image_session is None:
            labels = self.tracked_frame(frame_index, 0, z_index)
            return np.zeros(labels.shape, dtype=np.uint8)
        return self.image_session.display_frame(frame_index, channel, z_index)

    def tracked_frame(self, frame_index: int = 0, channel: int | str = 0, z_index: int = 0,) -> NDArray[Any]:
        """

        Return one selected ``YX`` plane from the tracking artifact.

        """
        selection: list[int | slice] = [slice(None)] * self._tracks.ndim
        for axis, value in (("T", frame_index),
                            ("C", self._resolve_channel(channel)),
                            ("Z", z_index),):
            if axis in self._axes:
                if value < 0 or value >= self._axis_size(axis):
                    raise IndexError(f"{axis} index {value} is outside the tracking artifact.")
                selection[self._axes.index(axis)] = value
            elif value != 0:
                raise IndexError(f"Tracking artifact has no {axis} axis.")
        plane = self._tracks[tuple(selection)]
        remaining = "".join(axis for axis in self._axes if axis not in {"T", "C", "Z"})
        if remaining != "YX":
            raise ValueError(f"A tracking plane must resolve to YX; got {remaining!r}.")
        return plane

    def track_centroids(self, channel: int | str = 0, z_index: int = 0,) -> dict[int, NDArray[np.float64]]:
        """

        Return cached centroid observations for every nonzero track.

        """
        channel_index = self._resolve_channel(channel)
        cache_key = (channel_index, z_index)
        cached = self._centroid_cache.get(cache_key)
        if cached is None:
            cached = calculate_track_centroids(self.tracked_frame,
                                                frame_count=self.frame_count,
                                                channel_index=channel_index,
                                                z_index=z_index,)
            self._centroid_cache[cache_key] = cached
        return cached

    def save_rendered_display(self,
                              *,
                              label: str,
                              channel: int | str,
                              z_index: int,
                              show_paths: bool,
                              path_extent: str,
                              thickness: int,
                              show_centroids: bool,
                              path_color_mode: str,
                              path_color: str,
                              mask_visible: bool,
                              mask_opacity: float,
                              display_metadata: dict[str, Any],
                              ) -> Path:
        """

        Render and save an RGB tracking visualization.

        """
        normalized_label = self._validate_output_label(label)
        output_path = self.source_path.with_name(f"fits_track_{normalized_label}.tif")
        selected_channel = self._resolve_channel(channel)
        output = render_tracking_display(self._tracks,
                                        frame_count=self.frame_count,
                                        channel_count=self._axis_size("C"),
                                        plane_count=self.plane_count,
                                        selected_channel=selected_channel,
                                        selected_z=z_index,
                                        tracked_frame=self.tracked_frame,
                                        centroids_for=self.track_centroids,
                                        plane_selection=self._plane_selection,
                                        show_paths=show_paths,
                                        path_extent=path_extent,
                                        thickness=thickness,
                                        show_centroids=show_centroids,
                                        path_color_mode=path_color_mode,
                                        path_color=path_color,
                                        mask_visible=mask_visible,
                                        mask_opacity=mask_opacity,)
        metadata = {"tracking_viewer_display": display_metadata}
        payload = self._reader.build_payload(export_channels=self._channel_labels,
                                            artifact_type="tracking_visualization",
                                            created_by=DIST_FITS,
                                            custom_metadata=metadata,
                                            ).with_fitsio(axes=f"{self._axes}S")
        return self._reader.save_array(output, metadata=payload, output_path=output_path)

    def _plane_selection(self, frame_index: int, channel_index: int, z_index: int,) -> tuple[int | slice, ...]:
        """

        Build an index for one frame, channel, and Z plane.

        """
        selection: list[int | slice] = [slice(None)] * self._tracks.ndim
        for axis, value in (("T", frame_index),
                            ("C", channel_index),
                            ("Z", z_index),):
            if axis in self._axes:
                selection[self._axes.index(axis)] = value
        return tuple(selection)

    @staticmethod
    def _validate_output_label(label: str) -> str:
        """

        Validate and normalize a tracking-display output label.

        """
        normalized = label.strip() or "path"
        invalid = frozenset('<>:"/\\|?*').intersection(normalized)
        if normalized.endswith(".") or invalid or any(ord(char) < 32 for char in normalized):
            raise ValueError(f"Invalid tracking display label: {label!r}.")
        return normalized

    def _resolve_channel(self, channel: int | str) -> int:
        """

        Resolve a tracking channel index or label.

        """
        if isinstance(channel, int):
            return channel
        return self._channel_labels.index(channel)

    def _axis_size(self, axis: str) -> int:
        """

        Return an axis size, defaulting to one when absent.

        """
        if axis not in self._axes:
            return 1
        return self._tracks.shape[self._axes.index(axis)]
