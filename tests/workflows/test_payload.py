from fits.settings.models import SettingsModel
from fits.workflows.payload import build_payload
from fits.workflows.provenance import StepProfile


def test_build_payload_combines_settings_and_provenance() -> None:
    settings = SettingsModel(enabled=True, overwrite=True)
    step_profile = StepProfile(distribution="io", step_name="convert")

    payload = build_payload(settings, step_profile, "ben", "fits_array")

    assert payload["enabled"] is True
    assert payload["overwrite"] is True
    assert payload["distribution"] == "io"
    assert payload["step_name"] == "convert"
    assert payload["user_name"] == "ben"
    assert payload["output_name"] == "fits_array"


def test_build_payload_includes_default_overwrite() -> None:
    settings = SettingsModel(enabled=False)
    step_profile = StepProfile(distribution="core", step_name="noop")

    payload = build_payload(
        settings=settings,
        step_profile=step_profile,
        user_name="user",
        output_name="out",
    )

    assert payload["overwrite"] is False
    
def test_build_payload_step_profile_overrides_settings_on_conflict() -> None:
    # Only if your models can actually conflict; example key "step_name"
    settings = SettingsModel(enabled=True, overwrite=True, step_name="wrong")  # type: ignore
    step_profile = StepProfile(distribution="io", step_name="convert")

    payload = build_payload(settings, step_profile, "ben", "fits_array")

    assert payload["step_name"] == "convert"