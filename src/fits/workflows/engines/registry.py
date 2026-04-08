from dataclasses import dataclass
from typing import Any, Callable, Generic, Literal, Mapping, TypeVar

import fits.environment.constant as cst
from fits.environment.state import ExperimentState
from fits.settings.models import ConvertSettings, SettingsModel, SegmentSettings, BGSubSettings
from fits.workflows.engines.provenance import StepProfile
from fits.workflows.convert import run_convert, convert_one
from fits.workflows.bg_sub import run_bg_sub, bg_sub_one
from fits.workflows.segment import run_segment, segment_one


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)

BatchRunner = Callable[[FitsSettings, list[ExperimentState], StepProfile, cst.FitsName], list[ExperimentState]]
TaskPool = Literal["cpu", "gpu"]
ItemRunner = Callable[[FitsSettings, ExperimentState, StepProfile, cst.FitsName], list[ExperimentState]]
SingleStateRunner = Callable[[FitsSettings, ExperimentState, StepProfile, cst.FitsName], ExperimentState]


def _wrap_single_state_runner(runner: SingleStateRunner[FitsSettings]) -> ItemRunner[FitsSettings]:
    def wrapped(settings: FitsSettings, exp_state: ExperimentState, step_profile: StepProfile, output_name: cst.FitsName) -> list[ExperimentState]:
        return [runner(settings, exp_state, step_profile, output_name)]

    return wrapped

@dataclass(frozen=True)
class StepSpec(Generic[FitsSettings]):
    name: str
    settings_model: type[FitsSettings]
    output_name: cst.FitsName
    batch_runner: BatchRunner[FitsSettings]
    item_runner: ItemRunner[FitsSettings]
    distribution: str
    pool: TaskPool
    
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
                    batch_runner=run_convert,
                    item_runner=convert_one,
                    distribution=cst.DIST_IO,
                    pool="cpu"),
    cst.STEP_BG_SUB: StepSpec(
                    name=cst.STEP_BG_SUB,
                    settings_model=BGSubSettings,
                    output_name=cst.FITS_ARRAY_NAME, 
                    batch_runner=run_bg_sub,
                    item_runner=_wrap_single_state_runner(bg_sub_one),
                    distribution=cst.DIST_BG_SUB,
                    pool="cpu"),
    cst.STEP_SEGMENT: StepSpec(
                    name=cst.STEP_SEGMENT,
                    settings_model=SegmentSettings,
                    output_name=cst.FITS_MASK_NAME,
                    batch_runner=run_segment,
                    item_runner=_wrap_single_state_runner(segment_one),
                    distribution=cst.DIST_SEG,
                    pool="gpu"),}