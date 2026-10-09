"""Desktop counters mirror terminal batch/conveyor bars, including branching."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.batch import run_batch_workflow
from fits.workflows.runtime.progress import RunProgress
from fits.workflows.runtime.progress.display import DisplayProgress
from fits.workflows.runtime.scheduler import run_workflow_scheduler


class TerminalBar:
    def __init__(self, total, **kwargs):
        self.completed = 0
        self.total = total

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def advance(self):
        self.completed += 1

    def update(self, *, total):
        self.total = total


def test_elapsed_resets_per_step_and_freezes_on_failure(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr('fits.workflows.runtime.progress.display.monotonic', lambda: clock[0])
    display = DisplayProgress()
    assert display.snapshot() is None
    with display.task('Convert', 2):
        display.advance()
        clock[0] = 15
        snapshot = display.snapshot()
        assert snapshot is not None and snapshot.elapsed == 5 and snapshot.active
    clock[0] = 20
    snapshot = display.snapshot()
    assert snapshot is not None and snapshot.elapsed == 5 and not snapshot.active
    with pytest.raises(RuntimeError), display.task('Segment', 3):
        clock[0] = 22
        raise RuntimeError('failed')
    clock[0] = 100
    snapshot = display.snapshot()
    assert snapshot is not None and snapshot.elapsed == 2 and not snapshot.active
    assert snapshot.name == 'Segment' and snapshot.completed == 0 and snapshot.total == 3


@pytest.mark.parametrize('mode', ['batch', 'conveyor'])
def test_workflow_display_matches_rich_counters_with_output_branches(monkeypatch, mode):
    progress = RunProgress()
    bars = []
    observations = []

    def bar(**kwargs):
        terminal = TerminalBar(**kwargs)
        bars.append(terminal)
        return terminal

    def runner(settings, state, profile):
        snapshot = progress.display.snapshot()
        assert snapshot is not None and snapshot.active
        observations.append(snapshot.name)
        output = state.with_complete_step(
            step_name=profile.step_name, artifact_kind='image',
            artifact_path=state.workdir / 'fits_array.tif')
        return [output, output] if profile.step_name == 'convert' else [output]

    registry = {}
    for name in ('convert', 'segment'):
        registry[name] = SimpleNamespace(
            profile=SimpleNamespace(step_name=name), item_runner=runner,
            is_interactive=False, pool='cpu', max_concurrency=None,
            model_validate=lambda params: SimpleNamespace(
                execution='serial', workers=1, ordered_execution=False))
    config = {name: {'enabled': True, 'params': {}} for name in registry}
    states = [ExperimentState.init(Path('/tmp'), Path('/tmp/display.nd2'))]
    if mode == 'batch':
        monkeypatch.setattr('fits.workflows.runtime.batch.api.WORKFLOW_ORDER', list(registry))
        monkeypatch.setattr('fits.workflows.runtime.batch.api.REGISTRY', registry)
        monkeypatch.setattr('fits.workflows.runtime.batch.execution.pbar', bar)
        result = run_batch_workflow(config, states, run_progress=progress)
        assert observations == ['Convert', 'Segment', 'Segment']
        assert [(item.completed, item.total) for item in bars] == [(1, 1), (2, 2)]
    else:
        monkeypatch.setattr('fits.workflows.runtime.scheduler.planning.WORKFLOW_ORDER', list(registry))
        monkeypatch.setattr('fits.workflows.runtime.scheduler.planning.REGISTRY', registry)
        monkeypatch.setattr('fits.workflows.runtime.scheduler.api.pbar', bar)
        result = run_workflow_scheduler(config, states, run_progress=progress)
        assert observations == ['Pipeline'] * 3
        assert (bars[0].completed, bars[0].total) == (3, 3)
    assert len(result) == 2
    snapshot = progress.display.snapshot()
    assert snapshot is not None and not snapshot.active
    assert (snapshot.completed, snapshot.total) == (bars[-1].completed, bars[-1].total)
