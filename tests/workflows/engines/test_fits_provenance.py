from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.models import build_provenance_stamp


def test_step_profile_holds_distribution_and_step_name() -> None:
    step_profile = StepProfile(distribution="io", step_name="convert")
    assert step_profile.distribution == "io"
    assert step_profile.step_name == "convert"


def test_build_provenance_stamp_contains_core_fields() -> None:
    stamp = build_provenance_stamp("fits")
    assert stamp["distribution"] == "fits"
    assert "version" in stamp
    assert "timestamp" in stamp