from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import pytest

from fits.environment.state import ExperimentState
from fits.workflows.execute import run_workflow


@dataclass
class DummySettings:
    value: int = 0


class DummyStepSpec:
    def __init__(self, name: str):
        self.name = name
        self.output_name = f"{name}_out"
        self.distribution = "test"
        self.step_profile = type("SP", (), {"step_name": name})()  # minimal shape
        self.validate_calls: list[Mapping[str, Any]] = []
        self.runner_calls: list[tuple[Any, list[ExperimentState], Any, str]] = []

    def model_validate(self, params: Mapping[str, Any]) -> DummySettings:
        self.validate_calls.append(params)
        return DummySettings(value=params.get("value", 0))

    def runner(self, settings: DummySettings, exp_states: list[ExperimentState], step_profile: Any, output_name: str):
        self.runner_calls.append((settings, exp_states, step_profile, output_name))
        # mutate states in a traceable way: set last_step
        return [st.replace(last_step=step_profile.step_name) for st in exp_states]


def test_run_workflow_runs_enabled_steps_in_order(monkeypatch) -> None:
    # Patch workflow order to have two steps
    monkeypatch.setattr("fits.workflows.execute.WORKFLOW_ORDER", ["convert", "other"])  # adjust module path

    convert = DummyStepSpec("convert")
    other = DummyStepSpec("other")

    monkeypatch.setattr(
        "fits.workflows.execute.REGISTRY",
        {"convert": convert, "other": other},
    )

    states = [ExperimentState(original_image=Path("a.nd2"))]

    user_cfg = {
        "convert": (True, {"value": 1}),
        "other": (True, {"value": 2}),
    }

    out = run_workflow(user_cfg, states)

    # validate called with params
    assert convert.validate_calls == [{"value": 1}]
    assert other.validate_calls == [{"value": 2}]

    # runners called in order
    assert len(convert.runner_calls) == 1
    assert len(other.runner_calls) == 1

    # exp_states threaded through: second step receives output of first
    (_, states_passed_to_convert, _, _) = convert.runner_calls[0]
    (_, states_passed_to_other, _, _) = other.runner_calls[0]
    assert states_passed_to_convert == states
    assert states_passed_to_other == [st.replace(last_step="convert") for st in states]

    # final output has last step of final runner
    assert [s.last_step for s in out] == ["other"]


def test_run_workflow_skips_disabled_step(monkeypatch) -> None:
    monkeypatch.setattr("fits.workflows.execute.WORKFLOW_ORDER", ["convert"])
    convert = DummyStepSpec("convert")
    monkeypatch.setattr("fits.workflows.execute.REGISTRY", {"convert": convert})

    states = [ExperimentState(original_image=Path("a.nd2"))]
    user_cfg = {"convert": (False, {"value": 1})}

    out = run_workflow(user_cfg, states)

    assert out == states
    assert convert.validate_calls == []
    assert convert.runner_calls == []


def test_run_workflow_skips_missing_step_in_registry(monkeypatch) -> None:
    monkeypatch.setattr("fits.workflows.execute.WORKFLOW_ORDER", ["convert"])
    monkeypatch.setattr("fits.workflows.execute.REGISTRY", {})  # missing

    states = [ExperimentState(original_image=Path("a.nd2"))]
    user_cfg = {"convert": (True, {"value": 1})}

    out = run_workflow(user_cfg, states)
    assert out == states


def test_run_workflow_default_user_cfg_when_step_missing(monkeypatch) -> None:
    # If user_cfg has no key, it uses default (False, {}) and skips
    monkeypatch.setattr("fits.workflows.execute.WORKFLOW_ORDER", ["convert"])
    convert = DummyStepSpec("convert")
    monkeypatch.setattr("fits.workflows.execute.REGISTRY", {"convert": convert})

    states = [ExperimentState(original_image=Path("a.nd2"))]
    user_cfg = {}  # no entry

    out = run_workflow(user_cfg, states)

    assert out == states
    assert convert.validate_calls == []
    assert convert.runner_calls == []
