from __future__ import annotations
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
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
    input_alternatives: tuple[ArtifactType, ...] = ()
    additional_artifacts: tuple[ArtifactType, ...] = ()


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)
TaskPool = Literal["cpu", "gpu"]
ItemRunner = Callable[[FitsSettings, ExperimentState, StepProfile], list[ExperimentState]]
StepKind = Literal["automatic", "interactive"]


@dataclass(frozen=True, slots=True)
class StepSpec(Generic[FitsSettings]):
    """
    Bind a step profile to its settings, runner, and execution requirements.
    """
    profile: StepProfile
    settings_model: type[FitsSettings]
    item_runner: ItemRunner[FitsSettings] | None
    pool: TaskPool
    kind: StepKind = "automatic"
    max_concurrency: int | None = None

    def __post_init__(self) -> None:
        """
        Validate and normalize the initialized fields.
        """
        if self.max_concurrency is not None and self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if self.kind == "automatic" and self.item_runner is None:
            raise ValueError("Automatic workflow steps require an item runner.")
        if self.kind == "interactive" and self.item_runner is not None:
            raise ValueError("Interactive workflow steps cannot define an item runner.")

    @property
    def is_interactive(self) -> bool:
        """
        Return whether this step must be completed through a UI interaction.
        """
        return self.kind == "interactive"

    def model_validate(self, params: Mapping[str, Any]) -> FitsSettings:
        """
        Validate step parameters using the registered settings model.
        """
        return self.settings_model.model_validate(params)


def item_runner_for(spec: StepSpec[FitsSettings]) -> ItemRunner[FitsSettings]:
    """
    Return an automatic runner and reject accidental interactive execution.
    """
    runner = spec.item_runner
    if runner is None:
        raise ValueError(f"Step {str(spec.profile.step_name)!r} requires the FITS GUI.")
    return partial(_run_scoped, runner)


def _run_scoped(runner: ItemRunner[FitsSettings],
                settings: FitsSettings,
                state: ExperimentState,
                profile: StepProfile,
                ) -> list[ExperimentState]:
    """
    Run scheduled work, bypassing imported stages only when they are not overwritten.
    """
    if state.execution_scope is not None:
        steps = state.execution_scope.get(state.workdir, ())
        if profile.step_name not in steps:
            return [state]
    # Migration depends on StepProfile through provenance/input resolution.
    from fits.workflows.file_management.migration import checkpoint_complete
    if checkpoint_complete(state, profile, getattr(settings, 'overwrite', False)):
        return [state]
    return runner(settings, state, profile)


def require_automatic_specs(specs: Iterable[StepSpec[Any]]) -> None:
    """
    Reject interactive steps before starting a headless workflow engine.
    """
    interactive = [str(spec.profile.step_name)
                   for spec in specs if spec.is_interactive]
    if interactive:
        names = ", ".join(repr(name) for name in interactive)
        raise ValueError(f"Interactive step(s) {names} require the FITS GUI.")
