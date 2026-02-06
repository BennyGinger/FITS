from pathlib import Path
from typing import Any

from fits.environment.state import ExperimentState
from fits.workflows.provenance import StepProfile
from fits.settings.models import SettingsModel


def build_payload(settings: SettingsModel, step_profile: StepProfile, user_name: str, output_name: str) -> dict[str, Any]:
    
    provenance_info = step_profile.dump()
    payload = settings.model_dump()
    payload.update(provenance_info)
    payload['user_name'] = user_name
    payload['output_name'] = output_name
    return payload