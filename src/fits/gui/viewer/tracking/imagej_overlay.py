"""Create ImageJ annotations without modifying image pixels or writing files."""

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from roifile import ImagejRoi, ROI_OPTIONS, ROI_SUBTYPE, ROI_TYPE

from fits.gui.viewer.tracking.colors import hex_rgb, track_rgb
from fits.gui.viewer.tracking.crop_geometry import CropBounds, clip_polyline


def _color(rgb: tuple[int, int, int], opacity: float = 1.0) -> bytes:
    return bytes((round(255 * min(max(opacity, 0.0), 1.0)), *rgb))


def _shape_roi(segments: list[float], color: bytes) -> ImagejRoi:
    return ImagejRoi(
        roitype=ROI_TYPE.RECT, shape_roi_size=len(segments),
        multi_coordinates=np.asarray(segments, dtype=np.float32), fill_color=color)


def _mask_rois(labels: NDArray[Any], track_ids: frozenset[int] | None,
               opacity: float) -> list[ImagejRoi]:
    """Encode horizontal pixel runs as filled rectangles, retaining holes/islands.

    ImageJ ShapeRoi segments use Java PathIterator codes: move=0, line=1,
    close=4. Each track is one compound shape, with exact pixel boundaries.
    """
    shapes: dict[int, list[float]] = {}
    for y, row in enumerate(labels):
        boundaries = np.flatnonzero(np.r_[True, row[1:] != row[:-1], True])
        for left, right in zip(boundaries[:-1], boundaries[1:], strict=True):
            track_id = int(row[left])
            if track_id == 0 or (track_ids is not None and track_id not in track_ids):
                continue
            segments = shapes.setdefault(track_id, [])
            segments.extend((0, left, y, 1, right, y, 1, right, y + 1,
                             1, left, y + 1, 4))
    rois = []
    for track_id, segments in shapes.items():
        roi = _shape_roi(segments, _color(track_rgb(track_id), opacity))
        roi.name = f"Mask {track_id}"
        rois.append(roi)
    return rois


def _marker_roi(x: float, y: float, size: int, color: bytes) -> ImagejRoi:
    """Use native ovals so overlapping centroid markers remain solid."""
    radius = size / 2
    return ImagejRoi(
        roitype=ROI_TYPE.OVAL, options=ROI_OPTIONS.SUB_PIXEL_RESOLUTION,
        xd=x - radius, yd=y - radius, widthd=float(size), heightd=float(size),
        left=int(np.floor(x - radius)), top=int(np.floor(y - radius)),
        right=int(np.ceil(x + radius)), bottom=int(np.ceil(y + radius)),
        fill_color=color)


def build_tracking_overlays(
        *, frame_count: int, channel: int, z_index: int,
        tracked_frame: Callable[[int, int, int], NDArray[Any]],
        centroids: dict[int, NDArray[np.float64]],
        show_paths: bool, path_extent: str, thickness: int,
        show_centroids: bool, marker_size: int,
        path_color_mode: str, path_color: str,
        mask_visible: bool, mask_opacity: float,
        track_ids: frozenset[int] | None,
        path_track_ids: frozenset[int] | None,
        selected_track_ids: frozenset[int], track_id_mode: str,
        crop_xy: CropBounds | None = None,
        ) -> list[bytes]:
    """Serialize a selected tracking plane across time, visible on all channels.

    ImageJ uses one-based Z/time positions; channel zero means every channel.
    Masks sit below trajectories, and explicit text ROIs sit above both.
    """
    overlays: list[bytes] = []

    def append(roi: ImagejRoi, frame: int | None) -> None:
        roi.c_position = 0
        roi.z_position = z_index + 1
        roi.t_position = 0 if frame is None else frame + 1
        overlays.append(roi.tobytes())

    visible_tracks = {}
    for track_id, points in centroids.items():
        if track_ids is not None and track_id not in track_ids:
            continue
        if crop_xy is not None:
            points = points.copy()
            points[:, 1:3] -= np.asarray(crop_xy[:2])
        visible_tracks[track_id] = points
    width = crop_xy[2] - crop_xy[0] if crop_xy is not None else 0
    height = crop_xy[3] - crop_xy[1] if crop_xy is not None else 0
    if mask_visible and mask_opacity > 0:
        for frame in range(frame_count):
            labels = tracked_frame(frame, channel, z_index)
            if crop_xy is not None:
                x0, y0, x1, y1 = crop_xy
                labels = labels[y0:y1, x0:x1]
            for roi in _mask_rois(labels, track_ids, mask_opacity):
                append(roi, frame)

    if show_paths:
        frames = [None] if path_extent == "full" else list(range(frame_count))
        # Draw selected paths last, just as the viewer's white highlight layer.
        path_ids = sorted(visible_tracks, key=lambda track: track in selected_track_ids)
        for frame in frames:
            for track_id in path_ids:
                if path_track_ids is not None and track_id not in path_track_ids:
                    continue
                points = visible_tracks[track_id]
                if frame is not None:
                    points = points[:np.searchsorted(points[:, 0], frame, side="right")]
                if not len(points):
                    continue
                rgb = (hex_rgb(path_color) if path_color_mode == "single"
                       else track_rgb(track_id))
                color = _color((255, 255, 255) if track_id in selected_track_ids else rgb)
                if len(points) > 1:
                    pieces = (clip_polyline(points[:, 1:3], width, height)
                              if crop_xy is not None else [points[:, 1:3]])
                    for piece in pieces:
                        # ImageJ uses miter joins for a multi-point polyline.
                        # At sharp turns these form long spikes, so store each
                        # edge as a native two-point ROI with no join.
                        for edge in zip(piece[:-1], piece[1:], strict=True):
                            roi = ImagejRoi.frompoints(edge, name=f"Path {track_id}")
                            roi.roitype = ROI_TYPE.POLYLINE
                            roi.options = (ROI_OPTIONS.SUB_PIXEL_RESOLUTION
                                           | ROI_OPTIONS.SCALE_STROKE_WIDTH)
                            roi.stroke_color = color
                            roi.float_stroke_width = float(thickness)
                            append(roi, frame)
                if show_centroids:
                    for _, x, y in points:
                        radius = marker_size / 2
                        if crop_xy is not None and not (-radius < x < width + radius
                                                        and -radius < y < height + radius):
                            continue
                        roi = _marker_roi(float(x), float(y), marker_size, color)
                        roi.name = f"Centroids {track_id}"
                        append(roi, frame)

    if track_id_mode != "none":
        for track_id, points in visible_tracks.items():
            if track_id_mode == "selected" and track_id not in selected_track_ids:
                continue
            for frame, x, y in points:
                text = str(track_id)
                left, top = round(x + 4), round(y - 18)
                right, bottom = left + 9 * len(text) + 4, top + 16
                if crop_xy is not None and (right <= 0 or bottom <= 0 or left >= width or top >= height):
                    continue
                roi = ImagejRoi(
                    roitype=ROI_TYPE.RECT, subtype=ROI_SUBTYPE.TEXT,
                    name=f"ID {track_id}", text=text, text_name="SansSerif", text_size=12,
                    left=left, top=top, right=right, bottom=bottom,
                    stroke_color=_color(track_rgb(track_id)),
                    fill_color=_color((20, 20, 20), 190 / 255))
                append(roi, int(frame))
    return overlays
