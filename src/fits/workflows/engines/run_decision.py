from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Generic, TypeVar

from fits_io.client import FitsIO

from fits.environment.state import ExperimentState


T = TypeVar("T")


@dataclass(slots=True, frozen=True)
class RunDecision(Generic[T]):
    requested_items: list[T]
    completed_items: list[T]
    missing_items: list[T]

    @property
    def is_complete(self) -> bool:
        return len(self.missing_items) == 0


def _init_run(requested_items: Sequence[T], completed_items: Sequence[T], overwrite: bool) -> RunDecision[T]:
    requested = list(requested_items)
    completed = [] if overwrite else list(completed_items)
    missing = requested if overwrite else [item for item in requested if item not in completed]
    return RunDecision(requested_items=requested, completed_items=completed, missing_items=missing)


def _load_mask_completed_items(exp_state: ExperimentState) -> list[int]:
    if exp_state.masks is None or not exp_state.masks.exists():
        return []
    reader = FitsIO.from_path(exp_state.masks)
    raw = reader.fits_metadata.get("mask_source_channel_indices")
    if raw is None:
        raise ValueError(f"Mask artifact at {exp_state.masks} is missing required metadata field 'mask_source_channel_indices'.")
    return [int(i) for i in raw]


def decide_run(exp_state: ExperimentState, step_name: str, overwrite: bool, requested_items: Sequence[int] | None = None) -> RunDecision[int | str]:
    if requested_items is None:
        completed_step_items: list[str] = []
        if step_name in exp_state.completed_steps and exp_state.image is not None and exp_state.image.exists():
            completed_step_items = [step_name]
        return _init_run([step_name], completed_step_items, overwrite)
    completed_mask_items = _load_mask_completed_items(exp_state)
    return _init_run(requested_items, completed_mask_items, overwrite)
