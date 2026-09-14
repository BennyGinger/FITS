from __future__ import annotations

from pathlib import Path
from typing import Any
import colorsys

import numpy as np
from numpy.typing import NDArray
from skimage.draw import disk as raster_disk, line as raster_line
from skimage.morphology import dilation, disk as disk_footprint

from fits.environment.constant import DIST_FITS, FITS_ARRAY_NAME, FITS_MASK_TRACK
from fits.sessions.image import FitsImageSession
from fits_io import FitsIO


class TrackingViewerSession:
    """Read a tracked-label artifact and its optional sibling image."""

    def __init__(self, tracking_path: str | Path) -> None:
        self.source_path = Path(tracking_path).expanduser().resolve()
        if not self.source_path.is_file() or self.source_path.name != FITS_MASK_TRACK:
            raise ValueError(f"Select a tracking artifact named {FITS_MASK_TRACK!r}.")
        reader = FitsIO.from_path(self.source_path)
        self._reader = reader
        result = reader.get_array()
        self._tracks = np.asarray(result.array)
        self._centroid_cache: dict[
            tuple[int, int], dict[int, NDArray[np.float64]]
        ] = {}
        self._axes = result.axes
        self._channel_labels = tuple(reader.channel_labels)
        if len(self._axes) != self._tracks.ndim or not {"Y", "X"}.issubset(self._axes):
            raise ValueError(
                f"Tracking axes {self._axes!r} do not match a YX label movie "
                f"with shape {self._tracks.shape}.")
        channel_count = self._axis_size("C")
        if not self._channel_labels:
            self._channel_labels = tuple(f"Channel {index + 1}" for index in range(channel_count))
        if len(self._channel_labels) != channel_count:
            raise ValueError(
                f"Tracking has {channel_count} channels but "
                f"{len(self._channel_labels)} channel labels.")
        image_path = self.source_path.with_name(FITS_ARRAY_NAME)
        self.image_session = FitsImageSession(image_path) if image_path.is_file() else None

    @property
    def axes(self) -> str:
        return self._axes

    @property
    def shape(self) -> tuple[int, ...]:
        return self._tracks.shape

    @property
    def channel_labels(self) -> tuple[str, ...]:
        """Channels available for the optional raw-image display."""
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

    def display_frame(self, frame_index: int = 0, channel: int | str = 0,
                      z_index: int = 0) -> NDArray[Any]:
        if self.image_session is None:
            labels = self.tracked_frame(frame_index, 0, z_index)
            return np.zeros(labels.shape, dtype=np.uint8)
        return self.image_session.display_frame(frame_index, channel, z_index)

    def tracked_frame(self, frame_index: int = 0, channel: int | str = 0,
                      z_index: int = 0) -> NDArray[Any]:
        selection: list[int | slice] = [slice(None)] * self._tracks.ndim
        for axis, value in (("T", frame_index), ("C", self._resolve_channel(channel)),
                            ("Z", z_index)):
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

    def track_centroids(
        self, channel: int | str = 0, z_index: int = 0,
    ) -> dict[int, NDArray[np.float64]]:
        """Return cached ``(frame, x, y)`` centroids for each nonzero track."""
        channel_index = self._resolve_channel(channel)
        cache_key = (channel_index, z_index)
        cached = self._centroid_cache.get(cache_key)
        if cached is not None:
            return cached

        observations: dict[int, list[tuple[float, float, float]]] = {}
        for frame_index in range(self.frame_count):
            labels = np.asarray(
                self.tracked_frame(frame_index, channel_index, z_index))
            present, inverse = np.unique(labels, return_inverse=True)
            inverse = inverse.ravel()
            rows, columns = np.indices(labels.shape)
            counts = np.bincount(inverse)
            row_sums = np.bincount(inverse, weights=rows.ravel())
            column_sums = np.bincount(inverse, weights=columns.ravel())
            for position, label in enumerate(present):
                track_id = int(label)
                if track_id == 0:
                    continue
                observations.setdefault(track_id, []).append((
                    float(frame_index),
                    float(column_sums[position] / counts[position]),
                    float(row_sums[position] / counts[position]),
                ))
        result = {
            track_id: np.asarray(points, dtype=np.float64)
            for track_id, points in observations.items()
        }
        self._centroid_cache[cache_key] = result
        return result

    def save_rendered_display(
        self, *, label: str, channel: int | str, z_index: int,
        show_paths: bool, path_extent: str, thickness: int, show_centroids: bool,
        path_color_mode: str, path_color: str,
        mask_visible: bool, mask_opacity: float,
        display_metadata: dict[str, Any],
    ) -> Path:
        """Save an RGB rendering of masks, trajectories, and optional raw image."""
        normalized_label = self._validate_output_label(label)
        output_path = self.source_path.with_name(f"fits_track_{normalized_label}.tif")
        selected_channel = self._resolve_channel(channel)
        output = np.zeros((*self._tracks.shape, 3), dtype=np.uint8)
        for frame_index in range(self.frame_count):
            for channel_index in range(self._axis_size("C")):
                for plane_index in range(self.plane_count):
                    labels = self.tracked_frame(frame_index, channel_index, plane_index)
                    rendered = np.zeros((*labels.shape, 3), dtype=np.uint8)
                    if mask_visible:
                        rendered = self._blend_masks(rendered, labels, mask_opacity)
                    if (show_paths and channel_index == selected_channel
                            and plane_index == z_index):
                        self._draw_paths(
                            rendered, frame_index, channel_index, plane_index,
                            path_extent, thickness, show_centroids,
                            path_color_mode, path_color)
                    output[(*self._plane_selection(
                        frame_index, channel_index, plane_index), slice(None))] = rendered

        metadata = {"tracking_viewer_display": display_metadata}
        payload = self._reader.build_payload(
            export_channels=self._channel_labels,
            artifact_type="tracking_visualization",
            created_by=DIST_FITS,
            custom_metadata=metadata,)
        payload = payload.with_fitsio(axes=f"{self._axes}S")
        return self._reader.save_array(
            output,
            metadata=payload,
            output_path=output_path,)

    @classmethod
    def _blend_masks(
        cls, image: NDArray[np.uint8], labels: NDArray[Any], opacity: float,
    ) -> NDArray[np.uint8]:
        rendered = image.astype(float)
        alpha = min(max(float(opacity), 0.0), 1.0)
        for label in np.unique(labels):
            track_id = int(label)
            if track_id == 0:
                continue
            selected = labels == label
            color = np.asarray(cls._track_rgb(track_id), dtype=float)
            rendered[selected] = rendered[selected] * (1.0 - alpha) + color * alpha
        return rendered.astype(np.uint8)

    def _draw_paths(
        self, rendered: NDArray[np.uint8], frame_index: int,
        channel_index: int, z_index: int, path_extent: str, thickness: int,
        show_centroids: bool, color_mode: str, single_color: str,
    ) -> None:
        centroids = self.track_centroids(channel_index, z_index)
        for track_id in sorted(centroids):
            points = centroids[track_id]
            visible = (points if path_extent == "full"
                       else points[points[:, 0] <= frame_index])
            pixels = self._rasterized_path(
                visible, rendered.shape[:2], thickness, show_centroids)
            color = (self._hex_rgb(single_color) if color_mode == "single"
                     else self._track_rgb(track_id))
            rendered[pixels] = color

    @staticmethod
    def _track_rgb(track_id: int) -> tuple[int, int, int]:
        hue = (track_id * 0.61803398875) % 1.0
        return tuple(int(value * 255) for value in colorsys.hsv_to_rgb(hue, 0.75, 1.0))

    @staticmethod
    def _hex_rgb(color: str) -> tuple[int, int, int]:
        value = color.lstrip("#")
        if len(value) != 6:
            raise ValueError(f"Invalid RGB color {color!r}.")
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))

    @staticmethod
    def _rasterized_path(
        points: NDArray[np.float64], shape: tuple[int, int],
        thickness: int, show_centroids: bool,
    ) -> NDArray[np.bool_]:
        canvas = np.zeros(shape, dtype=bool)
        rounded = np.rint(points[:, [2, 1]]).astype(int) if len(points) else np.empty((0, 2), int)
        for start, end in zip(rounded[:-1], rounded[1:], strict=True):
            rows, columns = raster_line(start[0], start[1], end[0], end[1])
            valid = ((rows >= 0) & (rows < shape[0])
                     & (columns >= 0) & (columns < shape[1]))
            canvas[rows[valid], columns[valid]] = True
        radius = max(0, int(thickness) // 2)
        if radius:
            canvas = dilation(canvas, disk_footprint(radius))
        if show_centroids:
            marker_radius = max(2, radius + 1)
            for row, column in rounded:
                rows, columns = raster_disk((row, column), marker_radius, shape=shape)
                canvas[rows, columns] = True
        return canvas

    def _plane_selection(
        self, frame_index: int, channel_index: int, z_index: int,
    ) -> tuple[int | slice, ...]:
        selection: list[int | slice] = [slice(None)] * self._tracks.ndim
        for axis, value in (("T", frame_index), ("C", channel_index), ("Z", z_index)):
            if axis in self._axes:
                selection[self._axes.index(axis)] = value
        return tuple(selection)

    @staticmethod
    def _validate_output_label(label: str) -> str:
        normalized = label.strip() or "path"
        invalid = frozenset('<>:"/\\|?*').intersection(normalized)
        if normalized.endswith(".") or invalid or any(ord(char) < 32 for char in normalized):
            raise ValueError(f"Invalid tracking display label: {label!r}.")
        return normalized

    def _resolve_channel(self, channel: int | str) -> int:
        return channel if isinstance(channel, int) else self._channel_labels.index(channel)

    def _axis_size(self, axis: str) -> int:
        return self._tracks.shape[self._axes.index(axis)] if axis in self._axes else 1
