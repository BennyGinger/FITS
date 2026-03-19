from dataclasses import dataclass
from typing import Any, Callable, Generic, Mapping, TypeVar

import fits.environment.constant as cst
from fits.environment.state import ExperimentState
from fits.settings.models import ConvertSettings, SettingsModel, SegmentSettings
from fits.workflows.convert import run_convert
from fits.workflows.engines.provenance import StepProfile
from fits.workflows.segment import run_segment


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)

Runner = Callable[[FitsSettings, list[ExperimentState], StepProfile, cst.FitsName], list[ExperimentState]]

@dataclass(frozen=True)
class StepSpec(Generic[FitsSettings]):
    name: str
    settings_model: type[FitsSettings]
    output_name: cst.FitsName
    runner: Runner[FitsSettings]
    distribution: str
    
    @property
    def step_profile(self) -> StepProfile:
        return StepProfile(self.distribution, self.name)
    
    def model_validate(self, params: Mapping[str, Any]) -> SettingsModel:
        """Convenience method to validate settings using the associated settings model."""
        return self.settings_model.model_validate(params)
    

REGISTRY: dict[str, StepSpec[Any]] = {
    cst.STEP_CONVERT: StepSpec(
                    name=cst.STEP_CONVERT,
                    settings_model=ConvertSettings,
                    output_name=cst.FITS_ARRAY_NAME,
                    runner=run_convert,
                    distribution=cst.DIST_IO),
    cst.STEP_SEGMENT: StepSpec(
                    name=cst.STEP_SEGMENT,
                    settings_model=SegmentSettings,
                    output_name=cst.FITS_MASK_NAME,
                    runner=run_segment,
                    distribution=cst.DIST_SEG),}