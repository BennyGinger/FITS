from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, Mapping, TypeVar

from fits.environment.constant import ArtifactType, FitsName, StepName
from fits.workflows.experiments import ExperimentState
from fits.settings.models import SettingsModel


@dataclass(frozen=True, slots=True)
class StepProfile:
    """
    Describe a workflow step and the artifacts it consumes and produces.
    """
    step_name: StepName
    distribution: str
    input_artifact: ArtifactType
    output_artifact: ArtifactType
    output_name: FitsName


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)
TaskPool = Literal["cpu", "gpu"]
ItemRunner = Callable[[FitsSettings, ExperimentState, StepProfile], list[ExperimentState]]


@dataclass(frozen=True, slots=True)
class StepSpec(Generic[FitsSettings]):
    """
    Bind a step profile to its settings, runner, and execution requirements.
    """
    profile: StepProfile
    settings_model: type[FitsSettings]
    item_runner: ItemRunner[FitsSettings]
    pool: TaskPool
    max_concurrency: int | None = None

    def __post_init__(self) -> None:
        if self.max_concurrency is not None and self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")

    def model_validate(self, params: Mapping[str, Any]) -> FitsSettings:
        return self.settings_model.model_validate(params)
