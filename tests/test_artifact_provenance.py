from fits_io.metadata.models import FitsIOMeta


def test_revision_roundtrip_and_metadata_only_preservation():
    original = FitsIOMeta().new_revision()
    child = original.new_revision([{"artifact_path": "input.tif", "created_at": original.fits_io.created_at}])
    assert child.fits_io.created_at != original.fits_io.created_at
    reloaded = FitsIOMeta.from_dict(child.dump())
    assert reloaded.fits_io.created_at == child.fits_io.created_at
    renamed = reloaded.with_fitsio(channel_labels=["Renamed"])
    assert renamed.fits_io.created_at == child.fits_io.created_at
    assert renamed.fits_io.derived_from == child.fits_io.derived_from
