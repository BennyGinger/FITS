from fits.workflows.metadata.merge import merge_step_metadata


def test_merge_step_metadata_merges_channel_subkeys() -> None:
    existing = {
        "channels": {
            "GFP": {"method": "a", "radius": 5},
            "RFP": {"method": "b"},
        },
        "settings_hash": "old",
    }
    update = {
        "channels": {
            "GFP": {"radius": 7, "sigma": 2.0},
            "DAPI": {"method": "c"},
        },
        "settings_hash": "new",
    }

    out = merge_step_metadata(existing, update)

    assert out["settings_hash"] == "new"
    assert out["channels"]["GFP"] == {"method": "a", "radius": 7, "sigma": 2.0}
    assert out["channels"]["RFP"] == {"method": "b"}
    assert out["channels"]["DAPI"] == {"method": "c"}
