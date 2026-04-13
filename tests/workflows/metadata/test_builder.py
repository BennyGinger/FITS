from fits.workflows.metadata.provenance import StepProfile
from fits.workflows.metadata.builder import build_step_project_metadata


def test_build_step_project_metadata_creates_pipeline_and_step_blocks() -> None:
    profile = StepProfile(distribution="fits", step_name="convert")

    out = build_step_project_metadata(
        existing_project_metadata=None,
        step_profile=profile,
        user_name="ben",
        step_metadata={"z_projection": "max"},
    )

    assert out["pipeline"]["distribution"] == "fits"
    assert out["pipeline"]["user_name"] == "ben"
    assert "version" in out["pipeline"]
    assert "convert" in out["steps"]
    assert out["steps"]["convert"]["distribution"] == "fits"
    assert out["steps"]["convert"]["z_projection"] == "max"
    assert "timestamp" in out["steps"]["convert"]


def test_build_step_project_metadata_merges_channel_metadata() -> None:
    profile = StepProfile(distribution="fits", step_name="bg_sub")
    existing = {
        "steps": {
            "bg_sub": {
                "channels": {
                    "GFP": {"radius": 5}
                }
            }
        }
    }

    out = build_step_project_metadata(
        existing_project_metadata=existing,
        step_profile=profile,
        user_name="ben",
        channel_metadata={"GFP": {"sigma": 2.0}, "RFP": {"radius": 3}},
    )

    channels = out["steps"]["bg_sub"]["channels"]
    assert channels["GFP"] == {"radius": 5, "sigma": 2.0}
    assert channels["RFP"] == {"radius": 3}


def test_build_step_project_metadata_uses_fixed_pipeline_distribution() -> None:
    profile = StepProfile(distribution="fits-io", step_name="convert")

    out = build_step_project_metadata(
        existing_project_metadata=None,
        step_profile=profile,
        user_name="ben",
    )

    assert out["pipeline"]["distribution"] == "fits"
    assert out["steps"]["convert"]["distribution"] == "fits-io"
