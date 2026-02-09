from dataclasses import dataclass
from typing import Any, Callable, Generic, Mapping, TypeVar

from fits.environment.constant import FITS_ARRAY_NAME, DIST_IO, STEP_CONVERT
from fits.environment.state import ExperimentState
from fits.settings.models import ConvertSettings, SettingsModel
from fits.workflows.tasks.convert import run_convert
from fits.workflows.provenance import StepProfile


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)

Runner = Callable[[FitsSettings, list[ExperimentState], StepProfile, str], list[ExperimentState]]

@dataclass(frozen=True)
class StepSpec(Generic[FitsSettings]):
    name: str
    settings_model: type[FitsSettings]
    output_name: str
    runner: Runner[FitsSettings]
    distribution: str
    
    @property
    def step_profile(self) -> StepProfile:
        return StepProfile(self.distribution, self.name)
    
    def model_validate(self, params: Mapping[str, Any]) -> SettingsModel:
        """Convenience method to validate settings using the associated settings model."""
        return self.settings_model.model_validate(params)
    

REGISTRY: dict[str, StepSpec[Any]] = {
    STEP_CONVERT: StepSpec(
                    name=STEP_CONVERT,
                    settings_model=ConvertSettings,
                    output_name=FITS_ARRAY_NAME,
                    runner=run_convert,
                    distribution=DIST_IO)
    ,}