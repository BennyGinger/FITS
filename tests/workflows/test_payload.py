from fits.workflows.provenance import StepProfile
from fits.workflows.tasks.utils import build_fits_payload


def test_build_fits_payload_combines_kwargs_and_provenance() -> None:
    step_profile = StepProfile(distribution="io", step_name="convert")

    payload = build_fits_payload(
        step_profile,
        user_name="ben",
        output_name="fits_array",
        overwrite=True,
    )

    assert payload["overwrite"] is True
    assert payload["distribution"] == "io"
    assert payload["step_name"] == "convert"
    assert payload["user_name"] == "ben"
    assert payload["output_name"] == "fits_array"


def test_build_fits_payload_uses_step_profile_values() -> None:
    step_profile = StepProfile(distribution="core", step_name="noop")

    payload = build_fits_payload(
        step_profile,
        value=1,
    )

    assert payload["distribution"] == "core"
    assert payload["step_name"] == "noop"
    assert payload["value"] == 1