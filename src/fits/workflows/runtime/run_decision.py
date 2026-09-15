"""
Determine which whole-step or channel-level work remains to run.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
import logging

from fits.workflows.experiments import ExperimentState
from fits.workflows.definitions.models import StepProfile



logger = logging.getLogger(__name__)

WHOLE_STEP_ITEM = 0

@dataclass(slots=True, frozen=True)
class RunDecision:
    """
    Describe requested, previously completed, and still-pending work items.
    """
    requested_items: list[int]
    completed_items: list[int]
    pending_items: list[int]

    @property
    def is_complete(self) -> bool:
        """
        Return whether no requested work remains to be executed.
        """
        return len(self.pending_items) == 0


def _init_run(requested_items: Sequence[int], completed_items: Sequence[int], overwrite: bool) -> RunDecision:
    """
    Build a decision while applying the requested overwrite policy.
    """
    requested = list(requested_items)
    completed = [] if overwrite else list(completed_items)
    pending = requested if overwrite else [item for item in requested if item not in completed]
    return RunDecision(requested_items=requested, completed_items=completed, pending_items=pending)


def decide_run(exp_state: ExperimentState, 
               step_profile: StepProfile, 
               overwrite: bool, 
               requested_items: Sequence[int] | None = None
               ) -> RunDecision:
    """
    Resolve pending work for a whole step or selected channel indices.
    """
    step_name = step_profile.step_name
    artifact_kind = step_profile.output_artifact
    if requested_items is None:
        artifact_path = exp_state.artifact(artifact_kind)
        is_completed = (step_name in exp_state.completed_steps and
                        artifact_path is not None and
                        artifact_path.exists())
        completed_items = [WHOLE_STEP_ITEM] if is_completed else []
        return _init_run([WHOLE_STEP_ITEM], completed_items, overwrite)
        
    completed_channel_items = exp_state.completed_channels(step_name)
    return _init_run(requested_items, completed_channel_items, overwrite)
