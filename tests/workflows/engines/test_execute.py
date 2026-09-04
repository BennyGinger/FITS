from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pytest

from fits.environment.state import ExperimentState
from fits.settings.resolution import apply_overwrite_cascade
from fits.workflows.execute import run_workflow


@dataclass
class DummySettings:
    value: int = 0
    execution: str = "serial"
    workers: int | None = None
    ordered_execution: bool = False


class DummyStepSpec:
    def __init__(self, name: str):
        self.profile = type("Profile", (), {"step_name": name})()
        self.validate_calls: list[Mapping[str, Any]] = []
        self.runner_calls: list[tuple[DummySettings, ExperimentState, Any]] = []

    def model_validate(self, params: Mapping[str, Any]) -> DummySettings:
        self.validate_calls.append(params)
        return DummySettings(value=params.get("value", 0))

    def item_runner(
            self,
            settings: DummySettings,
            state: ExperimentState,
            profile: Any,
            ) -> list[ExperimentState]:
        self.runner_calls.append((settings, state, profile))
        return [state.with_complete_step(
            step_name=profile.step_name,
            artifact_kind="image",
            artifact_path=state.workdir / f"{profile.step_name}.tif",)]


class DummyProgress:
    def __enter__(self) -> "DummyProgress":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def advance(self) -> None:
        return None


def make_state() -> ExperimentState:
    run_dir = Path("/tmp")
    return ExperimentState.init(run_dir, run_dir / "a.nd2")


def test_run_workflow_runs_enabled_steps_in_order(monkeypatch) -> None:
    convert = DummyStepSpec("convert")
    other = DummyStepSpec("other")
    monkeypatch.setattr("fits.workflows.execute.WORKFLOW_ORDER", ["convert", "other"])
    monkeypatch.setattr(
        "fits.workflows.execute.REGISTRY", {"convert": convert, "other": other})
    monkeypatch.setattr(
        "fits.workflows.execute.pbar", lambda **kwargs: DummyProgress())

    states = [make_state()]
    result = run_workflow({
        "convert": {"enabled": True, "params": {"value": 1}},
        "other": {"enabled": True, "params": {"value": 2}},
    }, states)

    assert convert.validate_calls == [{"value": 1}]
    assert other.validate_calls == [{"value": 2}]
    assert convert.runner_calls[0][1] is states[0]
    assert other.runner_calls[0][1].last_step == "convert"
    assert result[0].last_step == "other"


def test_run_workflow_skips_disabled_or_missing_config(monkeypatch) -> None:
    spec = DummyStepSpec("convert")
    monkeypatch.setattr("fits.workflows.execute.WORKFLOW_ORDER", ["convert"])
    monkeypatch.setattr("fits.workflows.execute.REGISTRY", {"convert": spec})
    states = [make_state()]

    assert run_workflow({}, states) == states
    assert run_workflow({"convert": {"enabled": False}}, states) == states
    assert spec.validate_calls == []


def test_run_workflow_rejects_enabled_step_missing_from_registry(monkeypatch) -> None:
    monkeypatch.setattr("fits.workflows.execute.WORKFLOW_ORDER", ["convert"])
    monkeypatch.setattr("fits.workflows.execute.REGISTRY", {})

    with pytest.raises(ValueError, match="missing from the registry"):
        run_workflow({"convert": {"enabled": True}}, [make_state()])


def test_apply_overwrite_cascade_propagates_downstream() -> None:
    resolved = apply_overwrite_cascade({
        "convert": {"enabled": True, "params": {"overwrite": True}},
        "segment": {"enabled": True, "params": {}},
    }, ["convert", "segment"])

    assert resolved["convert"]["params"]["overwrite"] is True
    assert resolved["segment"]["params"]["overwrite"] is True
