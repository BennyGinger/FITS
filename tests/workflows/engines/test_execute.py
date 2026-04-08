from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fits.environment.state import ExperimentState
from fits.workflows.engines.execute import (
    first_effective_overwrite_step,
    resolve_effective_workflow_cfg,
    run_workflow,
)


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

    def batch_runner(self, settings: DummySettings, exp_states: list[ExperimentState], step_profile: Any, output_name: str):
        self.runner_calls.append((settings, exp_states, step_profile, output_name))
        return [st.with_completed_step(step_profile.step_name) for st in exp_states]


def _state() -> ExperimentState:
    run_dir = Path("/tmp")
    return ExperimentState.init(run_dir, run_dir / "a.nd2")


def test_run_workflow_runs_enabled_steps_in_order(monkeypatch) -> None:
    monkeypatch.setattr("fits.workflows.engines.execute.WORKFLOW_ORDER", ["convert", "other"])

    convert = DummyStepSpec("convert")
    other = DummyStepSpec("other")

    monkeypatch.setattr(
        "fits.workflows.engines.execute.REGISTRY",
        {"convert": convert, "other": other},
    )

    states = [_state()]

    user_cfg = {
        "convert": {"enabled": True, "params": {"value": 1}},
        "other": {"enabled": True, "params": {"value": 2}},
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
    assert all(st.last_step == "convert" for st in states_passed_to_other)

    # final output has last step of final runner
    assert [s.last_step for s in out] == ["other"]


def test_run_workflow_skips_disabled_step(monkeypatch) -> None:
    monkeypatch.setattr("fits.workflows.engines.execute.WORKFLOW_ORDER", ["convert"])
    convert = DummyStepSpec("convert")
    monkeypatch.setattr("fits.workflows.engines.execute.REGISTRY", {"convert": convert})

    states = [_state()]
    user_cfg = {"convert": {"enabled": False, "params": {"value": 1}}}

    out = run_workflow(user_cfg, states)

    assert out == states
    assert convert.validate_calls == []
    assert convert.runner_calls == []


def test_run_workflow_skips_missing_step_in_registry(monkeypatch) -> None:
    monkeypatch.setattr("fits.workflows.engines.execute.WORKFLOW_ORDER", ["convert"])
    monkeypatch.setattr("fits.workflows.engines.execute.REGISTRY", {})

    states = [_state()]
    user_cfg = {"convert": {"enabled": True, "params": {"value": 1}}}

    out = run_workflow(user_cfg, states)
    assert out == states


def test_run_workflow_default_user_cfg_when_step_missing(monkeypatch) -> None:
    monkeypatch.setattr("fits.workflows.engines.execute.WORKFLOW_ORDER", ["convert"])
    convert = DummyStepSpec("convert")
    monkeypatch.setattr("fits.workflows.engines.execute.REGISTRY", {"convert": convert})

    states = [_state()]
    user_cfg = {}

    out = run_workflow(user_cfg, states)

    assert out == states
    assert convert.validate_calls == []
    assert convert.runner_calls == []


def test_resolve_effective_workflow_cfg_cascades_overwrite() -> None:
    resolved = resolve_effective_workflow_cfg(
        {
            "convert": {"enabled": True, "params": {"overwrite": True}},
            "segment": {"enabled": True, "params": {}},
        },
        ["convert", "segment"],
    )

    assert resolved["convert"]["params"]["overwrite"] is True
    assert resolved["segment"]["params"]["overwrite"] is True


def test_first_effective_overwrite_step_returns_first_enabled_overwrite() -> None:
    step = first_effective_overwrite_step(
        {
            "convert": {"enabled": False, "params": {"overwrite": True}},
            "segment": {"enabled": True, "params": {"overwrite": True}},
        },
        ["convert", "segment"],
    )

    assert step == "segment"
