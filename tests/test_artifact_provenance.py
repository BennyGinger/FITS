from scope_io.metadata.models import ImageMetadata


def test_revision_roundtrip_and_metadata_only_preservation():
    original = ImageMetadata().new_revision()
    child = original.new_revision([{"artifact_path": "input.tif", "created_at": original.artifact.created_at}])
    assert child.artifact.created_at != original.artifact.created_at
    reloaded = ImageMetadata.from_dict(child.dump())
    assert reloaded.artifact.created_at == child.artifact.created_at
    renamed = reloaded.with_artifact(channel_labels=["Renamed"])
    assert renamed.artifact.created_at == child.artifact.created_at
    assert renamed.artifact.derived_from == child.artifact.derived_from
