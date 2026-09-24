"""Split resolved workflow steps into interactive execution phases."""

from dataclasses import dataclass
from typing import Any

from fits.environment.constant import StepName
from fits.workflows.runtime.progress import WorkflowStage
from fits.workflows.runtime.scheduler.planning import RuntimeStep


CONVERSION = {StepName.CONVERT}
PREPROCESSING = {StepName.REGISTER_TIME, StepName.REGISTER_CHANNEL, StepName.BG_SUB}
COMPUTATION = {StepName.SEGMENT, StepName.TRACK}
EDITING = {StepName.EDIT_TRACK}
ANALYSIS = {StepName.DISTANCE_PROFILE, StepName.EXTRACT}
SUPPORTED = CONVERSION | PREPROCESSING | COMPUTATION | EDITING | ANALYSIS


@dataclass(frozen=True, slots=True)
class InteractivePlan:
    """
    Resolved steps grouped by the phase that owns their execution.
    """
    conversion: tuple[RuntimeStep, ...]
    preprocessing: tuple[RuntimeStep, ...]
    computation: tuple[RuntimeStep, ...]
    editing: tuple[RuntimeStep, ...]
    analysis: tuple[RuntimeStep, ...]
    mask_collection_required: bool

    @classmethod
    def from_steps(cls, steps: list[RuntimeStep]) -> "InteractivePlan":
        unsupported = [step.spec.profile.step_name for step in steps
                       if step.spec.profile.step_name not in SUPPORTED]
        if unsupported:
            raise ValueError("An enabled step has no interactive pipeline phase.")
        settings = {step.spec.profile.step_name: step.settings for step in steps}
        extraction = settings.get(StepName.EXTRACT)
        masks_required = bool(settings.get(StepName.DISTANCE_PROFILE)
                                or (extraction and extraction.draw_ref_mask))
        select = lambda names: tuple(step for step in steps 
                                     if step.spec.profile.step_name in names)
        return cls(conversion=select(CONVERSION),
                    preprocessing=select(PREPROCESSING),
                    computation=select(COMPUTATION),
                    editing=select(EDITING),
                    analysis=select(ANALYSIS),
                    mask_collection_required=masks_required,)

    @property
    def settings(self) -> dict[StepName, Any]:
        return {step.spec.profile.step_name: step.settings
                for step in self.all_steps}

    @property
    def all_steps(self) -> tuple[RuntimeStep, ...]:
        return (self.conversion + self.preprocessing + self.computation
                + self.editing + self.analysis)

    @property
    def required_stages(self) -> set[WorkflowStage]:
        stages = set()
        if self.conversion:
            stages.add(WorkflowStage.CONVERT)
        if self.preprocessing:
            stages.add(WorkflowStage.PREPROCESS)
        if self.computation or self.editing:
            stages.add(WorkflowStage.PROCESS)
        if self.mask_collection_required:
            stages.add(WorkflowStage.DRAWING)
        if self.analysis:
            stages.add(WorkflowStage.ANALYSIS)
        return stages
