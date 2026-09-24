from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.scheduler import (
    resolve_runtime_steps,
    run_workflow_scheduler,
)


class DummyProgress:
    def __enter__(self) -> "DummyProgress":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def advance(self) -> None:
        return None

    def update(self, **kwargs: Any) -> None:
        return None


@dataclass
class DummyProfile:
    step_name: str


class DummyStepSpec:
    def __init__(self, name: str, runner: Any, pool: str = "cpu",
                 *, interactive: bool = False):
        self.profile = DummyProfile(name)
        self.item_runner = runner
        self.pool = pool
        self.max_concurrency = None
        self.is_interactive = interactive

    def model_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        return dict(params)


def make_state() -> ExperimentState:
    return ExperimentState.init(Path("/tmp"), Path("/tmp/a.nd2"))


def test_resolve_runtime_steps_uses_enabled_workflow_order(monkeypatch) -> None:
    spec = DummyStepSpec("convert", lambda *args: [])
    monkeypatch.setattr(
        "fits.workflows.runtime.scheduler.planning.WORKFLOW_ORDER",
        ["convert", "segment"],)
    monkeypatch.setattr(
        "fits.workflows.runtime.scheduler.planning.REGISTRY", {"convert": spec})

    resolved = resolve_runtime_steps({
        "convert": {"enabled": True, "params": {"overwrite": True}},
        "segment": {"enabled": False},
    })

    assert len(resolved) == 1
    assert resolved[0].spec is spec
    assert resolved[0].settings == {"overwrite": True}


def test_run_workflow_scheduler_returns_input_when_no_steps_enabled() -> None:
    states = [make_state()]
    assert run_workflow_scheduler({}, states) == states


def test_run_workflow_scheduler_runs_single_enabled_step(monkeypatch) -> None:
    def runner(settings, state, profile):
        return [state.with_complete_step(
            step_name=profile.step_name,
            artifact_kind="image",
            artifact_path=state.workdir / "fits_array.tif",)]

    spec = DummyStepSpec("convert", runner)
    monkeypatch.setattr(
        "fits.workflows.runtime.scheduler.planning.WORKFLOW_ORDER", ["convert"])
    monkeypatch.setattr(
        "fits.workflows.runtime.scheduler.planning.REGISTRY", {"convert": spec})
    monkeypatch.setattr(
        "fits.workflows.runtime.scheduler.api.pbar",
        lambda **kwargs: DummyProgress(),)

    result = run_workflow_scheduler(
        {"convert": {"enabled": True, "params": {}}}, [make_state()])

    assert result[0].last_step == "convert"


def test_resolve_runtime_steps_rejects_missing_registry_step(monkeypatch) -> None:
    monkeypatch.setattr(
        "fits.workflows.runtime.scheduler.planning.WORKFLOW_ORDER", ["convert"])
    monkeypatch.setattr("fits.workflows.runtime.scheduler.planning.REGISTRY", {})

    with pytest.raises(ValueError, match="missing from the registry"):
        resolve_runtime_steps({"convert": {"enabled": True}})


def test_scheduler_rejects_interactive_steps_before_submission(monkeypatch) -> None:
    spec = DummyStepSpec(
        "edit_track", None, interactive=True)
    monkeypatch.setattr(
        "fits.workflows.runtime.scheduler.planning.WORKFLOW_ORDER",
        ["edit_track"])
    monkeypatch.setattr(
        "fits.workflows.runtime.scheduler.planning.REGISTRY",
        {"edit_track": spec})

    with pytest.raises(ValueError, match="require the FITS GUI"):
        run_workflow_scheduler(
            {"edit_track": {"enabled": True, "params": {}}}, [make_state()])
