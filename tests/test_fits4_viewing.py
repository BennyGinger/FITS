"""Real-file coverage of current, compacted, branch and legacy viewing contracts."""
import numpy as np
import pytest
import tifffile
from scope_io import ScopeIO
from fits.environment import constant as cst
from fits.workflows.artifacts.provenance import require_writable
from fits.gui.viewer.tracking.session import TrackingViewerSession
from fits.workflows.artifacts.branch_masks import refresh_branch


def write(path, *, kind='image_raw', custom=None):
    original = path.parent / 'acquisition.tif'
    if not original.exists():
        tifffile.imwrite(original, np.ones((8, 8), dtype=np.uint16), photometric='minisblack')
    reader = ScopeIO.from_path(original)
    payload = reader.build_payload(export_channels='all', artifact_type=kind,
        custom_metadata={'pipeline_meta': {'version': '4.0.0'}, **(custom or {})}).new_revision()
    return reader.save_array(np.ones((8, 8), dtype=np.uint16), metadata=payload, output_path=path)


@pytest.mark.parametrize('name', [*cst.IMAGE_NAMES, *cst.MASK_NAMES, 'fits_ref_edge.tif', 'fits_roi_edge.tif'])
def test_viewer_loads_all_supported_artifacts(tmp_path, name):
    is_track = name in cst.TRACKING_NAMES or name == cst.FITS_MASKS_COMPACTED
    path = write(tmp_path / name, kind='tracking' if is_track else 'segmentation')
    session = TrackingViewerSession(path)
    assert session.is_tracking == is_track
    assert not session.read_only
    assert session.display_frame().shape == (8, 8)
    session.close()


def test_legacy_viewing_is_read_only(tmp_path):
    path = tmp_path / 'fits_track.tif'
    tifffile.imwrite(path, np.ones((8, 8), dtype=np.uint16), imagej=True)
    session = TrackingViewerSession(path)
    assert session.read_only
    with pytest.raises(ValueError, match='read-only'):
        session.save_edited_tracking()
    session.close()


def test_branch_metadata_refresh_preserves_pixels_and_geometry_boundary(tmp_path):
    custom = {'registration_revisions': {'register_channel': 'registration-1'}}
    image = write(tmp_path / cst.FITS_ARRAY_BGSUB, custom=custom)
    ref = write(tmp_path / 'fits_ref_edge.tif', kind=cst.ARTI_REF, custom=custom)
    old = ScopeIO.from_path(ref).reader.metadata.artifact.created_at
    refresh_branch(ref, image)
    assert ScopeIO.from_path(ref).reader.metadata.artifact.created_at == old
    np.testing.assert_array_equal(ScopeIO.from_path(ref).get_array().array, np.ones((8, 8)))
    # Intensity-only image writes retain registration revisions.
    write(image, custom=custom)
    refresh_branch(ref, image)
    write(image, custom={'registration_revisions': {'register_channel': 'registration-2'}})
    with pytest.raises(ValueError, match='Registration changed'):
        refresh_branch(ref, image)


_APP = None
@pytest.mark.parametrize('name,kind', [(cst.FITS_ARRAY_RAW, 'image_raw'),
    (cst.FITS_MASK_SEG, 'segmentation'), (cst.FITS_MASKS_COMPACTED, 'tracking'),
    ('fits_ref_edge.tif', cst.ARTI_REF), ('fits_roi_edge.tif', cst.ARTI_ROI)])
def test_real_gui_uses_artifact_specific_controls(tmp_path, name, kind):
    from PySide6.QtWidgets import QApplication
    from fits.gui.viewer.tracking import TrackingViewerWindow
    global _APP
    _APP = QApplication.instance() or QApplication([])
    write(tmp_path / cst.FITS_ARRAY_RAW)
    path = write(tmp_path / name, kind=kind)
    window = TrackingViewerWindow(tracking_path=path, editing_enabled=False)
    try:
        assert window._tracking_session is not None, window.status_label.text()
        assert window.filter_section.isHidden() == (kind != 'tracking')
        assert window.trajectory_section.isHidden() == (kind != 'tracking')
        assert window.mask_edit_section.isHidden()
    finally:
        window.close()
        window.deleteLater()
        _APP.processEvents()
