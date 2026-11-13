"""Explicit REF/ROI Save distinguishes drawing edits from geometry review."""
from pathlib import Path

import numpy as np
import pytest
import tifffile
from scope_io import ScopeIO
from scope_io.writers.metadata_update import rewrite_metadata

from fisch.tasks.reference_mask import ReferenceMaskSession
from fisch.tasks.roi_mask import RoiSession
from fisch.workflows.artifacts.branch_masks import geometry, refresh_branch
from fisch.workflows.artifacts.provenance import read_metadata

pytestmark = pytest.mark.usefixtures("current_format_tiffs")


def _source(tmp_path):
    source = tmp_path / "proc_array_reg.tif"
    tifffile.imwrite(source, np.arange(3 * 64, dtype=np.uint16).reshape(3, 8, 8),
                     imagej=True, metadata={"axes": "TYX"})
    _registration(source, "first")
    return source


def _registration(source, revision):
    metadata = read_metadata(source).with_custom_metadata({"registration_revisions": {"register_time": revision}})
    rewrite_metadata(source, metadata)


def _session(kind, source, saved=None):
    return (ReferenceMaskSession(source, reference_path=saved) if kind == "ref"
            else RoiSession(source, roi_path=saved))


def _plane(kind):
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[2:6, 2:6] = 1 if kind == "ref" else 4
    return mask


@pytest.mark.parametrize("kind", ["ref", "roi"])
def test_identical_save_is_noop_or_metadata_review(tmp_path, kind):
    source = _source(tmp_path)
    session = _session(kind, source)
    session.set_mask_plane(_plane(kind), frame_index=0)
    saved = session.save("wound")
    session.close()
    before = saved.read_bytes()
    stamp = saved.stat().st_mtime_ns
    pixels = ScopeIO.from_path(saved).get_array().array.copy()
    revision = read_metadata(saved).artifact.created_at
    session = _session(kind, source, saved)
    assert session.save("wound") == saved
    assert saved.read_bytes() == before
    assert saved.stat().st_mtime_ns == stamp
    session.close()
    _registration(source, "second")
    session = _session(kind, source, saved)
    # Opening/reviewing the old mask alone never accepts its geometry.
    with pytest.raises(ValueError, match="Registration changed"):
        refresh_branch(saved, source)
    assert saved.read_bytes() == before
    session.save("wound")  # No overwrite=True, so no GUI confirmation is requested.
    metadata = read_metadata(saved)
    assert metadata.artifact.created_at == revision
    assert geometry(metadata) == geometry(read_metadata(source))
    assert metadata.custom_metadata["geometry_review"]["previous_geometry"] == {"register_time": "first"}
    np.testing.assert_array_equal(ScopeIO.from_path(saved).get_array().array, pixels)
    np.testing.assert_array_equal(session.mask_plane(0), _plane(kind))
    refresh_branch(saved, source)  # Analysis now accepts this drawing.
    reviewed = saved.read_bytes()
    stamp = saved.stat().st_mtime_ns
    session.save("wound")
    assert saved.read_bytes() == reviewed
    assert saved.stat().st_mtime_ns == stamp
    session.close()


@pytest.mark.parametrize("kind", ["ref", "roi"])
def test_changed_pixels_require_confirmation_even_after_registration_changed(tmp_path, kind):
    source = _source(tmp_path)
    session = _session(kind, source)
    session.set_mask_plane(_plane(kind), frame_index=0)
    saved = session.save("wound")
    session.close()
    _registration(source, "second")
    session = _session(kind, source, saved)
    changed = _plane(kind)
    changed[1, 1] = 1 if kind == "ref" else 4
    session.set_mask_plane(changed, frame_index=0)
    before = saved.read_bytes()
    with pytest.raises(FileExistsError, match="different pixels"):
        session.save("wound")
    assert saved.read_bytes() == before  # Declining cannot accept geometry either.
    assert geometry(read_metadata(saved)) != geometry(read_metadata(source))
    session.save("wound", overwrite=True)
    np.testing.assert_array_equal(ScopeIO.from_path(saved).get_array().array[0], changed)
    assert geometry(read_metadata(saved)) == geometry(read_metadata(source))
    session.close()


def test_roi_manual_state_changes_are_pixel_changes(tmp_path):
    source = _source(tmp_path)
    session = RoiSession(source)
    mask = _plane("roi")
    session.set_mask_plane(mask, frame_index=0)
    saved = session.save("region")
    # State 5 and state 4 are both included, but preserve different manual decisions.
    mask[3, 3] = 5
    session.set_mask_plane(mask, frame_index=0)
    with pytest.raises(FileExistsError, match="different pixels"):
        session.save("region")
    session.close()


@pytest.mark.parametrize("kind", ["ref", "roi"])
def test_comparison_uses_completed_pixels_not_only_anchors(tmp_path, kind):
    source = _source(tmp_path)
    session = _session(kind, source)
    anchor = _plane(kind)
    if kind == "roi":
        anchor[anchor != 0] = 3  # ROI interpolation fills manual inclusion anchors.
    session.set_mask_plane(anchor, frame_index=0)
    session.set_mask_plane(anchor, frame_index=2)
    saved = session.save("wound", interpolation_axis="T")
    before = saved.read_bytes()
    # Session still has empty middle anchors; completed output is nevertheless identical.
    session.save("wound", interpolation_axis="T")
    assert saved.read_bytes() == before
    # Disabling completion changes final pixels, so requires confirmation.
    with pytest.raises(FileExistsError, match="different pixels"):
        session.save("wound")
    session.close()


@pytest.mark.parametrize("kind", ["ref", "roi"])
def test_multichannel_save_preserves_other_channel(tmp_path, kind):
    source = tmp_path / "proc_array_reg.tif"
    tifffile.imwrite(source, np.ones((3, 2, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={"axes": "TCYX"})
    _registration(source, "first")
    session = _session(kind, source)
    session.set_mask_plane(_plane(kind), frame_index=0, channel=0)
    session.set_mask_plane(_plane(kind), frame_index=2, channel=1)
    saved = session.save("wound", channel=0)
    session.save("wound", channel=1)
    before = saved.read_bytes()
    other = ScopeIO.from_path(saved).get_array().array[:, 1].copy()
    session.save("wound", channel=0)
    session.save("wound", channel=1)
    assert saved.read_bytes() == before
    changed = _plane(kind)
    changed[1, 1] = 1 if kind == "ref" else 4
    session.set_mask_plane(changed, frame_index=0, channel=0)
    with pytest.raises(FileExistsError):
        session.save("wound", channel=0)
    session.save("wound", channel=0, overwrite=True)
    np.testing.assert_array_equal(ScopeIO.from_path(saved).get_array().array[:, 1], other)
    session.close()
