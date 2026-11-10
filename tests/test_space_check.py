"""Stop numerical and file-management actions before low-space writes."""

from pathlib import Path
from typing import Any
import json

import numpy as np
import pytest
import tifffile

from fisch.environment import constant as cst
from fisch.environment.paths import experiment_state_path
from fisch.gui.settings import SettingsAdapter
from fisch.pipeline import start_pipeline
from fisch.tasks.common.preparation import resolve_step_run
from fisch.workflows.checks import space
from fisch.workflows.checks.pipeline import require_pipeline_space
from fisch.workflows.definitions.registry import REGISTRY
from fisch.workflows.experiments import ExperimentState
from fisch.workflows.file_management import api
from fisch.workflows.file_management.compaction import plan_compaction
from fisch.workflows.file_management.history import delete_history, restore_history, snapshots
from fisch.workflows.file_management.rebuild import ProcessingPlan
from test_file_management import legacy_run


def _full_disk(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Simulate a full destination volume without changing its real free space.
    """
    usage = space.shutil.disk_usage(root)
    monkeypatch.setattr(space.shutil, 'disk_usage', lambda path: usage._replace(free=0))


def test_pipeline_space_failure_keeps_source_and_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Reject a fresh pipeline before conversion, grouping, settings or log writes.
    """
    source = tmp_path / 'image.tif'
    tifffile.imwrite(source, np.ones((8, 8), dtype=np.uint16), photometric='minisblack')
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', ['Red'])
    settings = adapter.save_to_run_dir()
    before = {path: path.read_bytes() for path in (source, settings)}
    _full_disk(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='Not enough disk space.*Free space'):
        start_pipeline(settings, terminal_progress=False)
    assert all(path.read_bytes() == data for path, data in before.items())
    assert not (tmp_path / 'image').exists()
    assert not (tmp_path / '.pipeline/logs').exists()
    assert not list(tmp_path.rglob(cst.ARRAY_RAW))


def test_pending_output_estimate_respects_completion_and_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Count pending outputs using raw array size, excluding completed work.
    """
    original = tmp_path / 'image.nd2'
    original.write_bytes(b'raw' * 100)
    raw = tmp_path / cst.ARRAY_RAW
    raw.write_bytes(b'array' * 200)
    state = ExperimentState.init(tmp_path, original, run_dir=tmp_path).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=raw)
    estimates: list[int] = []

    def capture(root: Path, required: int, *, action: str) -> None:
        """
        Observe the shared estimate without depending on a machine's free space.
        """
        estimates.append(required)

    monkeypatch.setattr(space, 'require_free_space', capture)
    config: dict[str, Any] = {cst.StepName.CONVERT: {'enabled': True, 'params': {}},
                              cst.StepName.BG_SUB: {'enabled': True, 'params': {}}}
    require_pipeline_space(tmp_path, [state], config)
    assert estimates[-1] == raw.stat().st_size
    config[cst.StepName.CONVERT]['params']['overwrite'] = True
    require_pipeline_space(tmp_path, [state], config)
    assert estimates[-1] == 2 * raw.stat().st_size


def test_pending_step_rechecks_space_but_completed_step_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Stop a pending step if free space falls after the initial pipeline check.
    """
    original = tmp_path / 'image.tif'
    original.write_bytes(b'original')
    state = ExperimentState.init(tmp_path, original, run_dir=tmp_path)
    profile = REGISTRY[cst.StepName.BG_SUB].profile
    _full_disk(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='Not enough disk space'):
        resolve_step_run(state, profile, False)
    output = tmp_path / cst.ARRAY_BGSUB
    output.write_bytes(b'completed')
    state = state.with_complete_step(step_name=profile.step_name,
                                     artifact_kind=profile.output_artifact, artifact_path=output)
    assert resolve_step_run(state, profile, False).is_complete


@pytest.mark.parametrize('action', ['update', 'rebuild', 'processing', 'compact', 'restore'])
def test_file_actions_stop_on_full_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    """
    Reject reviewed writes and numerical callbacks while preserving active files.
    """
    legacy_run(tmp_path, masks=True)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    state = api.migrate(migration)[0]
    image = state.artifact(cst.ARTI_IMG)
    assert image is not None
    before = image.read_bytes()
    entry = snapshots(tmp_path)[0]
    calls: list[ProcessingPlan] = []
    if action == 'update':
        # Absolute saved references request a location update, independently of
        # combined-analysis membership checks.
        path = experiment_state_path(state.workdir)
        payload = json.loads(path.read_text())
        payload['artifacts'][cst.ARTI_RAW] = str(state.original_image)
        path.write_text(json.dumps(payload))
    _full_disk(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='Not enough disk space'):
        if action == 'update':
            api.plan_update(tmp_path)
        elif action == 'rebuild':
            api.plan_full_rebuild(tmp_path)
        elif action == 'processing':
            plan = ProcessingPlan(tmp_path, 'rebuild', {state.workdir: ('convert',)}, ())
            api.update_downstream(plan, calls.append)
        elif action == 'compact':
            plan_compaction(tmp_path)
        else:
            restore_history(tmp_path, entry)
    assert image.read_bytes() == before
    assert not calls
    assert entry.directory.is_dir()


def test_history_deletion_remains_available_on_full_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Allow users to reclaim retained-copy space without requiring another copy.
    """
    legacy_run(tmp_path)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    state = api.migrate(migration)[0]
    image = state.artifact(cst.ARTI_IMG)
    assert image is not None
    before = image.read_bytes()
    entries = snapshots(tmp_path)
    _full_disk(tmp_path, monkeypatch)
    delete_history(tmp_path, entries)
    assert not snapshots(tmp_path)
    assert image.read_bytes() == before
