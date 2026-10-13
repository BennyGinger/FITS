"""ImageJ overlay encoding and preservation of the complete raw hyperstack."""

from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO
from roifile import ImagejRoi, ROI_SUBTYPE, ROI_TYPE

from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_TRACK
from fits.gui.viewer.tracking.colors import track_rgb
from fits.gui.viewer.tracking.session import TrackingViewerSession


def make_experiment(directory: Path, dtype=np.uint16):
    directory.mkdir(parents=True, exist_ok=True)
    raw = np.arange(3 * 2 * 2 * 24 * 25, dtype=dtype).reshape(3, 2, 2, 24, 25)
    source = directory / FITS_ARRAY_NAME
    input_path = directory / "input.tif"
    tifffile.imwrite(input_path, raw, imagej=True, resolution=(2, 4),
                     metadata={"axes": "TZCYX", "unit": "micron", "finterval": 2.5,
                               "Labels": ["GFP", "RFP"]})
    FitsIO.from_path(input_path).save_array(
        raw, channel_labels=("GFP", "RFP"), output_path=source)
    labels = np.zeros((3, 2, 24, 25), dtype=np.uint16)
    for frame in range(3):
        labels[frame, 1, 4:9, 5 + frame:10 + frame] = 7
        labels[frame, 1, 5:8, 6 + frame:9 + frame] = 0  # A hole.
        labels[frame, 1, 12, 5 + frame] = 7  # A disconnected island.
        labels[frame, 1, 15:18, 18:21] = 11
    labels[:, 0, 2:4, 2:4] = 99  # Another Z plane must not enter the overlay.
    tracking = FitsIO.from_path(source).save_array(
        labels, channel_labels=("GFP", "RFP"), export_channels=("GFP",),
        output_path=directory / FITS_MASK_TRACK)
    return source, tracking, raw, labels


def display_options(**changes):
    options = dict(
        label="review", channel="GFP", z_index=1,
        show_paths=True, path_extent="built", thickness=2,
        show_centroids=True, marker_size=5,
        path_color_mode="track", path_color="#ffd700",
        mask_visible=True, mask_opacity=0.45,
        track_ids=None, path_track_ids=None,
        selected_track_ids=frozenset({7}), track_id_mode="selected",
        filtered=False, display_metadata={"raw_image_visible": False})
    options.update(changes)
    return options


def read_rois(path):
    with tifffile.TiffFile(path) as tif:
        encoded = tif.imagej_metadata.get("Overlays", [])
    if isinstance(encoded, bytes):
        encoded = [encoded]
    return [ImagejRoi.frombytes(roi) for roi in encoded]


@pytest.mark.parametrize("dtype", [np.uint16, np.float32])
def test_overlay_export_retains_raw_hyperstack_and_source_files(tmp_path, dtype):
    source, tracking, raw, labels = make_experiment(tmp_path, dtype)
    source_hash = sha256(source.read_bytes()).digest()
    tracking_hash = sha256(tracking.read_bytes()).digest()
    session = TrackingViewerSession(tracking)
    output = session.save_overlay_display(**display_options())
    assert output.name == "fits_track_overlay_review.tif"
    assert sha256(source.read_bytes()).digest() == source_hash
    assert sha256(tracking.read_bytes()).digest() == tracking_hash
    with tifffile.TiffFile(output) as tif:
        np.testing.assert_array_equal(tif.asarray(), raw)
        assert tif.asarray().dtype == raw.dtype
        assert tif.series[0].axes == "TZCYX"
        assert tif.pages[0].compression == tifffile.COMPRESSION.NONE
        assert tif.imagej_metadata["Labels"] == ["GFP", "RFP"]
        assert tif.imagej_metadata["finterval"] == 2.5
        assert tif.imagej_metadata["unit"] == "micron"
        assert tif.pages[0].tags["XResolution"].value == (2, 1)
        assert tif.pages[0].tags["YResolution"].value == (4, 1)
    metadata = FitsIO.from_path(output).metadata.custom_metadata["tracking_viewer_display"]
    assert metadata["output_mode"] == "imagej_overlay"
    assert metadata["raw_image_exported"] is True
    rois = read_rois(output)
    assert {roi.c_position for roi in rois} == {0}
    assert {roi.z_position for roi in rois} == {2}
    assert {roi.t_position for roi in rois} == {1, 2, 3}
    assert {roi.name for roi in rois} == {
        "Mask 7", "Mask 11", "Path 7", "Path 11", "Centroids 7", "Centroids 11", "ID 7"}
    for roi in rois:
        if roi.name == "Mask 7":
            # Reconstruct filled rectangles and compare every pixel, including holes.
            decoded = np.zeros(labels.shape[-2:], dtype=bool)
            for rectangle in roi.multi_coordinates.reshape(-1, 13):
                left, top, right, bottom = rectangle[[1, 2, 4, 8]].astype(int)
                decoded[top:bottom, left:right] = True
            np.testing.assert_array_equal(decoded, labels[roi.t_position - 1, 1] == 7)
            assert roi.fill_color == bytes((115, *track_rgb(7)))
        elif roi.name == "Path 7":
            assert roi.roitype == ROI_TYPE.POLYLINE
            assert roi.stroke_color == b"\xff\xff\xff\xff"
            assert roi.n_coordinates == 2
        elif roi.name == "ID 7":
            assert roi.subtype == ROI_SUBTYPE.TEXT
            assert roi.text == "7"


def test_filters_and_full_paths_only_affect_annotations(tmp_path):
    _, tracking, raw, _ = make_experiment(tmp_path)
    output = TrackingViewerSession(tracking).save_overlay_display(**display_options(
        track_ids=frozenset({7}), filtered=True, path_extent="full", track_id_mode="all"))
    assert output.name == "fits_track_overlay_filtered_review.tif"
    np.testing.assert_array_equal(tifffile.imread(output), raw)
    rois = read_rois(output)
    assert all(roi.name.endswith(" 7") for roi in rois)
    paths = [roi for roi in rois if roi.name == "Path 7"]
    assert len(paths) == 2
    assert {roi.t_position for roi in paths} == {0}  # Full path shared across all frames.


@pytest.mark.parametrize("selected", [frozenset(), frozenset({7})])
def test_selected_paths_and_ids_are_independent_of_masks(tmp_path, selected):
    _, tracking, _, _ = make_experiment(tmp_path)
    output = TrackingViewerSession(tracking).save_overlay_display(**display_options(
        path_track_ids=selected, selected_track_ids=selected))
    rois = read_rois(output)
    assert {roi.name for roi in rois if roi.name.startswith("Mask")} == {"Mask 7", "Mask 11"}
    other_names = {roi.name for roi in rois if not roi.name.startswith("Mask")}
    assert other_names == ({"Path 7", "Centroids 7", "ID 7"} if selected else set())


def test_hidden_paths_and_masks_still_allow_ids(tmp_path):
    _, tracking, _, _ = make_experiment(tmp_path)
    output = TrackingViewerSession(tracking).save_overlay_display(**display_options(
        show_paths=False, mask_visible=False, track_id_mode="all"))
    assert {roi.name for roi in read_rois(output)} == {"ID 7", "ID 11"}


def test_overlay_export_requires_raw_image(tmp_path):
    source, tracking, _, _ = make_experiment(tmp_path)
    source.unlink()
    with pytest.raises(ValueError, match="requires the sibling fits_array.tif"):
        TrackingViewerSession(tracking).save_overlay_display(**display_options())
    assert not (tmp_path / "fits_track_overlay_review.tif").exists()


def test_crop_preserves_all_raw_dimensions_and_aligns_masks_and_paths(tmp_path):
    source, tracking, raw, labels = make_experiment(tmp_path)
    original = source.read_bytes()
    session = TrackingViewerSession(tracking)
    before = {track: points.copy() for track, points in session.track_centroids(0, 1).items()}
    bounds = (6, 5, 20, 18)
    output = session.save_overlay_display(**display_options(crop_xy=bounds, track_id_mode="all"))
    assert output.name == "fits_track_overlay_review_cropped.tif"
    np.testing.assert_array_equal(tifffile.imread(output), raw[..., 5:18, 6:20])
    assert source.read_bytes() == original
    metadata = FitsIO.from_path(output).metadata.custom_metadata
    assert metadata["tracking_viewer_display"]["crop_xy"] == list(bounds)
    assert metadata["spatial_crops"][0]["source_shape"] == list(raw.shape)
    for roi in read_rois(output):
        assert roi.z_position == 2 and roi.c_position == 0
        if roi.name.startswith("Mask"):
            track = int(roi.name.split()[-1])
            decoded = np.zeros((13, 14), dtype=bool)
            for rectangle in roi.multi_coordinates.reshape(-1, 13):
                left, top, right, bottom = rectangle[[1, 2, 4, 8]].astype(int)
                decoded[top:bottom, left:right] = True
            np.testing.assert_array_equal(decoded, labels[roi.t_position - 1, 1, 5:18, 6:20] == track)
        elif roi.name.startswith("Path"):
            assert (roi.subpixel_coordinates >= 0).all()
            assert (roi.subpixel_coordinates[:, 0] <= 14).all()
            assert (roi.subpixel_coordinates[:, 1] <= 13).all()
    for track, points in session.track_centroids(0, 1).items():
        np.testing.assert_array_equal(points, before[track])


def test_export_keeps_crossing_path_segments_when_centroids_are_outside(tmp_path, monkeypatch):
    _, tracking, _, _ = make_experiment(tmp_path)
    session = TrackingViewerSession(tracking)
    monkeypatch.setattr(session, "track_centroids", lambda *args: {
        7: np.array([[0., 0., 12.], [1., 24., 12.]])})
    output = session.save_overlay_display(**display_options(
        crop_xy=(5, 5, 20, 18), mask_visible=False, show_centroids=False,
        track_id_mode="none", path_extent="full"))
    rois = read_rois(output)
    assert len(rois) == 1 and rois[0].name == "Path 7"
    np.testing.assert_allclose(rois[0].subpixel_coordinates, [[0, 7], [15, 7]])


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16, np.float32])
@pytest.mark.parametrize("labels,colors", [
    (("GFP",), ["00ff00"]),
    (("GFP", "unknown_dye", "DAPI"), ["00ff00", "ffffff", "0000ff"]),
])
def test_overlay_export_luts_for_single_and_mixed_channels(tmp_path, dtype, labels, colors):
    axes = "TYX" if len(labels) == 1 else "TCYX"
    shape = (2, 8, 9) if len(labels) == 1 else (2, len(labels), 8, 9)
    raw = np.arange(np.prod(shape), dtype=dtype).reshape(shape)
    input_path = tmp_path / "input.tif"
    tifffile.imwrite(input_path, raw, imagej=True, metadata={"axes": axes})
    source = FitsIO.from_path(input_path).save_array(
        raw, channel_labels=labels, output_path=tmp_path / FITS_ARRAY_NAME)
    masks = np.zeros((2, 8, 9), dtype=np.uint16)
    masks[:, 2:5, 2:5] = 7
    tracking = FitsIO.from_path(source).save_array(
        masks, export_channels=(labels[0],), output_path=tmp_path / FITS_MASK_TRACK)
    session = TrackingViewerSession(tracking)
    for bounds in (None, (1, 1, 8, 7)):
        output = session.save_overlay_display(**display_options(
            channel=labels[0], z_index=0, crop_xy=bounds))
        expected = raw if bounds is None else raw[..., 1:7, 1:8]
        with tifffile.TiffFile(output) as tif:
            np.testing.assert_array_equal(tif.asarray(), expected)
            assert tif.asarray().dtype == raw.dtype
            if len(labels) == 1:
                assert "ColorMap" in tif.pages[0].tags
            luts = np.asarray(tif.imagej_metadata["LUTs"]).reshape(len(labels), 3, 256)
            for lut, color in zip(luts, colors, strict=True):
                assert tuple(lut[:, -1]) == tuple(bytes.fromhex(color))
