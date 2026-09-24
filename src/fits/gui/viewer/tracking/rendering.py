"""RGB rendering of tracked masks and centroid trajectories."""

from collections.abc import Callable
import colorsys
from typing import Any

import numpy as np
from numpy.typing import NDArray

from fits.gui.viewer.tracking.trajectories import rasterize_path


def render_tracking_display(tracks: NDArray,
                            *,
                            frame_count: int,
                            channel_count: int,
                            plane_count: int,
                            selected_channel: int,
                            selected_z: int,
                            tracked_frame: Callable[[int, int, int], NDArray],
                            centroids_for: Callable[[int, int], dict[int, NDArray[np.float64]]],
                            plane_selection: Callable[[int, int, int], tuple[int | slice, ...]],
                            show_paths: bool,
                            path_extent: str,
                            thickness: int,
                            show_centroids: bool,
                            marker_size: int,
                            path_color_mode: str,
                            path_color: str,
                            mask_visible: bool,
                            mask_opacity: float,
                            ) -> NDArray[np.uint8]:
    """
    Render every tracking plane into an RGB array.
    """
    output = np.zeros((*tracks.shape, 3), dtype=np.uint8)
    for frame_index in range(frame_count):
        for channel_index in range(channel_count):
            for plane_index in range(plane_count):
                labels = tracked_frame(frame_index, channel_index, plane_index)
                rendered = np.zeros((*labels.shape, 3), dtype=np.uint8)
                if mask_visible:
                    rendered = blend_masks(rendered, labels, mask_opacity)
                if (show_paths and channel_index == selected_channel
                        and plane_index == selected_z):
                    draw_paths(rendered,
                                centroids_for(channel_index, plane_index),
                                frame_index=frame_index,
                                path_extent=path_extent,
                                thickness=thickness,
                                show_centroids=show_centroids,
                                marker_size=marker_size,
                                color_mode=path_color_mode,
                                single_color=path_color,)
                plane = plane_selection(frame_index, channel_index, plane_index)
                output[(*plane, slice(None))] = rendered
    return output


def render_selected_tracking_display(
        *,
        frame_count: int,
        selected_channel: int,
        selected_z: int,
        tracked_frame: Callable[[int, int, int], NDArray],
        centroids: dict[int, NDArray[np.float64]],
        show_paths: bool,
        path_extent: str,
        thickness: int,
        show_centroids: bool,
        marker_size: int,
        path_color_mode: str,
        path_color: str,
        mask_visible: bool,
        mask_opacity: float,
        track_ids: frozenset[int] | None,
        ) -> NDArray[np.uint8]:
    """Render the selected channel and Z plane across time."""
    frames: list[NDArray[np.uint8]] = []
    for frame_index in range(frame_count):
        labels = tracked_frame(frame_index, selected_channel, selected_z)
        if track_ids is not None:
            labels = np.where(np.isin(labels, tuple(track_ids)), labels, 0)
        rendered = np.zeros((*labels.shape, 3), dtype=np.uint8)
        if mask_visible:
            rendered = blend_masks(rendered, labels, mask_opacity)
        if show_paths:
            visible_centroids = (centroids if track_ids is None else
                                 {key: value for key, value in centroids.items()
                                  if key in track_ids})
            draw_paths(rendered, visible_centroids,
                       frame_index=frame_index, path_extent=path_extent,
                       thickness=thickness, show_centroids=show_centroids,
                       marker_size=marker_size,
                       color_mode=path_color_mode, single_color=path_color)
        frames.append(rendered)
    return np.stack(frames) if frame_count > 1 else frames[0]


def blend_masks(image: NDArray[np.uint8], labels: NDArray[Any], opacity: float,) -> NDArray[np.uint8]:
    """
    Blend labelled masks onto an RGB image.
    """
    rendered = image.astype(float)
    alpha = min(max(float(opacity), 0.0), 1.0)
    present, inverse = np.unique(labels, return_inverse=True)
    colors = np.asarray([
        (0, 0, 0) if label == 0 else track_rgb(int(label))
        for label in present
    ], dtype=float)
    overlay = colors[inverse].reshape((*labels.shape, 3))
    selected = labels != 0
    rendered[selected] = (rendered[selected] * (1.0 - alpha)
                          + overlay[selected] * alpha)
    return rendered.astype(np.uint8)


def draw_paths(rendered: NDArray[np.uint8],
                centroids: dict[int, NDArray[np.float64]],
                *,
                frame_index: int,
                path_extent: str,
                thickness: int,
                show_centroids: bool,
                marker_size: int,
                color_mode: str,
                single_color: str,
                ) -> None:
    """
    Draw visible track trajectories onto an RGB plane.
    """
    for track_id in sorted(centroids):
        points = centroids[track_id]
        visible = (points if path_extent == "full"
                    else points[points[:, 0] <= frame_index])
        height, width = rendered.shape[:2]
        pixels = rasterize_path(visible, 
                                (height, width), 
                                thickness, 
                                show_centroids,
                                marker_size)
        color = (hex_rgb(single_color)
                if color_mode == "single" else track_rgb(track_id))
        rendered[pixels] = color


def track_rgb(track_id: int) -> tuple[int, int, int]:
    """
    Generate a stable, distinct RGB colour for a track identifier.
    """
    hue = (track_id * 0.61803398875) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
    return int(red * 255), int(green * 255), int(blue * 255)


def hex_rgb(color: str) -> tuple[int, int, int]:
    """
    Convert a six-digit hexadecimal colour string to RGB.
    """
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid RGB color {color!r}.")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
