"""Dimension-based guards for optional registration and tracking steps."""

from pathlib import Path

import pytest

from fisch.environment.constant import StepName
from fisch.workflows.checks.models import RawInputReport
from fisch.workflows.checks.step_requirements import frame_count_summary, step_input_problems
from fisch.workflows.checks.step_requirements import require_workflow_steps, workflow_step_problems


@pytest.mark.parametrize("frames,channels,summary,affected", [
    ((1,), 1, "1", {StepName.TRACK, StepName.REGISTER_TIME, StepName.REGISTER_CHANNEL}),
    ((1, 5), 2, "≥ 1", {StepName.TRACK, StepName.REGISTER_TIME}),
    ((3, 5), 2, "≥ 3", set()),
    ((4, 4), 1, "4", {StepName.REGISTER_CHANNEL}),
])
def test_step_requirements_follow_all_series(frames: tuple[int, ...],
                                            channels: int,
                                            summary: str,
                                            affected: set[StepName],
                                            ) -> None:
    """
    Warn for minimum input dimensions while preserving unequal valid time series.
    """
    source = Path("sample.nd2")
    report = RawInputReport({source: channels}, {}, (), frame_counts={source: frames})
    assert frame_count_summary(report) == summary
    assert set(step_input_problems(report)) == affected


def test_channel_subset_and_unknown_dimensions() -> None:
    """
    Apply channel guards to exported subsets and avoid guessing absent metadata.
    """
    report = RawInputReport({Path("sample.nd2"): 3}, {}, ())
    assert set(step_input_problems(report, 1)) == {StepName.REGISTER_CHANNEL}
    assert not step_input_problems(None)
    assert frame_count_summary(None) == "—"


@pytest.mark.parametrize("segment,track,valid", [(False, False, False), (True, False, True), (False, True, True)])
def test_quantification_requires_an_included_mask_producer(segment: bool, track: bool, valid: bool) -> None:
    """
    Share the same Quantification inclusion requirement between GUI and CLI.
    """
    config = {StepName.EXTRACT: {"enabled": True}, StepName.SEGMENT: {"enabled": segment},
              StepName.TRACK: {"enabled": track}}
    assert (StepName.EXTRACT not in workflow_step_problems(config)) is valid
    if valid:
        require_workflow_steps(config)
    else:
        with pytest.raises(ValueError, match="Quantification requires Segmentation or Tracking"):
            require_workflow_steps(config)
