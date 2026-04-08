from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from fits.environment.state import ExperimentState
from fits.workflows.engines.scheduler import (
    _enabled_workflow_steps,
    _next_enabled_step,
    run_workflow_scheduler,
)


class DummyPbar:
    def __enter__(self) -> DummyPbar:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def advance(self) -> None:
        return None

    def update(self, **kwargs: Any) -> None:
        return None


@dataclass
class DummyStepSpec:
    name: str
    output_name: str
    step_profile: Any
    item_runner: Any
    pool: str = 'cpu'

    def model_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        return dict(params)


def test_enabled_workflow_steps_and_next_step_helpers() -> None:
    enabled = _enabled_workflow_steps(
        {
            'convert': {'enabled': True},
            'segment': {'enabled': False},
        }
    )

    assert enabled == ['convert']
    assert _next_enabled_step('convert', ['convert', 'segment']) == 'segment'
    assert _next_enabled_step('segment', ['convert', 'segment']) is None


def test_run_workflow_scheduler_returns_input_when_no_steps_enabled(monkeypatch) -> None:
    states = [ExperimentState.init(Path('/tmp'), Path('/tmp/a.nd2'))]
    monkeypatch.setattr('fits.workflows.engines.scheduler.get_ctx', lambda: object())

    assert run_workflow_scheduler({}, states) == states


def test_run_workflow_scheduler_runs_single_enabled_step(monkeypatch) -> None:
    states = [ExperimentState.init(Path('/tmp'), Path('/tmp/a.nd2'))]
    def runner(settings, exp_state, step_profile, output_name):
        return [exp_state.with_completed_step(step_profile.step_name)]

    convert_spec = DummyStepSpec(
        name='convert',
        output_name='fits_array.tif',
        step_profile=type('StepProfile', (), {'step_name': 'convert'})(),
        item_runner=runner,
        pool='cpu',
    )

    monkeypatch.setattr('fits.workflows.engines.scheduler.cst.WORKFLOW_ORDER', ['convert'])
    monkeypatch.setattr('fits.workflows.engines.scheduler.REGISTRY', {'convert': convert_spec})
    monkeypatch.setattr('fits.workflows.engines.scheduler.get_ctx', lambda: object())
    monkeypatch.setattr('fits.workflows.engines.scheduler.pbar', lambda **kwargs: DummyPbar())

    out = run_workflow_scheduler({'convert': {'enabled': True, 'params': {}}}, states)

    assert [state.last_step for state in out] == ['convert']


def test_run_workflow_scheduler_rejects_missing_enabled_registry_step(monkeypatch) -> None:
    states = [ExperimentState.init(Path('/tmp'), Path('/tmp/a.nd2'))]

    monkeypatch.setattr('fits.workflows.engines.scheduler.cst.WORKFLOW_ORDER', ['convert'])
    monkeypatch.setattr('fits.workflows.engines.scheduler.REGISTRY', {})
    monkeypatch.setattr('fits.workflows.engines.scheduler.get_ctx', lambda: object())

    with pytest.raises(ValueError, match='missing from workflow registry'):
        run_workflow_scheduler({'convert': {'enabled': True, 'params': {}}}, states)