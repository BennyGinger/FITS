from dataclasses import dataclass
from typing import Any, Callable, Generic, Mapping, TypeVar

from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_NAME, DIST_IO, DIST_SEG, STEP_CONVERT, STEP_SEGMENT, FitsName
from fits.environment.state import ExperimentState
from fits.settings.models import ConvertSettings, SettingsModel, SegmentSettings
from fits.workflows.tasks.convert import run_convert
from fits.workflows.provenance import StepProfile
from fits.workflows.tasks.segment import run_segment


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)

Runner = Callable[[FitsSettings, list[ExperimentState], StepProfile, FitsName], list[ExperimentState]]

@dataclass(frozen=True)
class StepSpec(Generic[FitsSettings]):
    name: str
    settings_model: type[FitsSettings]
    output_name: FitsName
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
                    distribution=DIST_IO),
    STEP_SEGMENT: StepSpec(
                    name=STEP_SEGMENT,
                    settings_model=SegmentSettings,
                    output_name=FITS_MASK_NAME,
                    runner=run_segment,
                    distribution=DIST_SEG),}