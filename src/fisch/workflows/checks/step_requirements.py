"""Relate acquisition dimensions to optional processing-step requirements."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from fisch.environment.constant import StepName
from fisch.workflows.checks.models import RawInputReport
from fisch.workflows.definitions.inputs import quantification_mask_kind


def workflow_step_problems(config: Mapping[str, Any]) -> dict[StepName, str]:
    """
    Describe inclusion requirements independently of files and GUI controls.
    """
    problems: dict[StepName, str] = {}
    try:
        quantification_mask_kind(config)
    except ValueError as error:
        problems[StepName.EXTRACT] = str(error)
    if not config.get(StepName.TRACK, {}).get("enabled"):
        problems[StepName.EDIT_TRACK] = "Edit tracking requires Tracking to be included in the workflow."
    return problems


def require_workflow_steps(config: Mapping[str, Any]) -> None:
    """
    Reject incompatible included steps before processing or artifact decisions.
    """
    from fisch.environment.constant import validate_workflow_order
    validate_workflow_order()
    errors = [message for step, message in workflow_step_problems(config).items()
              if config.get(step, {}).get("enabled")]
    if errors:
        raise ValueError("\n".join(errors))


def frame_count_summary(report: RawInputReport | None) -> str:
    """
    Summarize all series with an exact count or the minimum for mixed lengths.
    """
    counts = {count for values in report.frame_counts.values() for count in values} if report else set()
    if not counts:
        return "—"
    return str(min(counts)) if len(counts) == 1 else f"≥ {min(counts)}"


def step_input_problems(report: RawInputReport | None, exported_channels: int | None = None) -> dict[StepName, str]:
    """
    Identify steps that cannot process every input with the available dimensions.
    """
    if report is None:
        return {}
    problems: dict[StepName, str] = {}
    frames = [count for values in report.frame_counts.values() for count in values]
    if frames and min(frames) < 2:
        for step, title in ((StepName.TRACK, "Tracking"), (StepName.REGISTER_TIME, "Frame-shift registration")):
            problems[step] = (f"{title} requires at least 2 frames; at least one input experiment has only 1 frame. "
                              f"Disable {title} or use time-series inputs.")
    channels = exported_channels if exported_channels is not None else min(report.channel_counts.values(), default=0)
    if channels == 1:
        problems[StepName.REGISTER_CHANNEL] = (
            "Channel-shift registration requires at least 2 image channels; only 1 channel is available. "
            "Disable channel-shift registration or export more channels.")
    return problems
