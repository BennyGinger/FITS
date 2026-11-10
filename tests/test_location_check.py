"""Exercise location-only updates and context-aware rebuild scopes with real portable files."""

import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest
from scope_io import ScopeIO

from fits.pipeline import start_pipeline
from fits.environment import constant as cst
from fits.environment.paths import experiment_state_path
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.locations import inspect_locations
from fits.workflows.experiments import ExperimentState, discover_saved_states, save_experiment_state
from fits.workflows.file_management import api
from fits.workflows.artifacts.provenance import read_metadata
from scope_io.writers.metadata_update import rewrite_metadata
from test_file_management import legacy_run, mock_rebuild_processing


def test_moved_acquisition_updates_only_master_tags(tmp_path: Path) -> None:
    """
    Detect moved condition folders, preserve portable table bytes, and clear the warning after updating.
    """
    legacy_run(tmp_path, masks=True)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    state = api.migrate(migration)[0]
    assert not inspect_locations(tmp_path).needs_update
    assert api.plan_update(tmp_path) is None
    table = state.workdir / cst.FITS_QUANTI_NAME
    original = table.read_bytes()
    assert not any(name.startswith('condition_level_') for name in pd.read_parquet(table))
    moved = tmp_path / 'treated' / state.original_image.parent.name
    moved.parent.mkdir()
    shutil.move(state.original_image.parent, moved)
    report = inspect_locations(tmp_path)
    assert report.needs_update
    assert all(issue.path.name == cst.MASTER_QUANTI_NAME for issue in report.issues)
    assert 'treated/image/image_s1' in report.describe()
    plan = api.plan_update(tmp_path)
    assert plan is not None
    api.update(plan)
    assert (moved / state.workdir.name / table.name).read_bytes() == original
    master = pd.read_parquet(tmp_path / cst.MASTER_QUANTI_NAME)
    assert master['condition_level_1'].tolist() == ['treated']
    assert master['experiment_id'].tolist() == ['treated/image/image_s1']
    assert not inspect_locations(tmp_path).needs_update
    assert api.plan_update(tmp_path) is None


def test_absent_master_does_not_require_tag_update(tmp_path: Path) -> None:
    """
    Leave coherent portable experiments alone when no master has been generated.
    """
    legacy_run(tmp_path, masks=True)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    state = api.migrate(migration)[0]
    (tmp_path / cst.MASTER_QUANTI_NAME).unlink()
    moved = tmp_path / 'treated' / 'image'
    moved.parent.mkdir()
    shutil.move(state.original_image.parent, moved)
    assert not inspect_locations(tmp_path).needs_update
    assert api.plan_update(tmp_path) is None


def test_absolute_state_reference_can_be_updated_without_master(tmp_path: Path) -> None:
    """
    Detect and repair nonportable state references even when no quantification exists.
    """
    legacy_run(tmp_path)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    state = api.migrate(migration)[0]
    state_path = experiment_state_path(state.workdir)
    payload = json.loads(state_path.read_text())
    payload['artifacts'][cst.ARTI_RAW] = str(state.original_image)
    state_path.write_text(json.dumps(payload))
    assert inspect_locations(tmp_path).needs_update
    plan = api.plan_update(tmp_path)
    assert plan is not None
    api.update(plan)
    assert not inspect_locations(tmp_path).needs_update
    assert not Path(json.loads(state_path.read_text())['artifacts'][cst.ARTI_RAW]).is_absolute()


def _current_series(template: ExperimentState, name: str, root: Path) -> ExperimentState:
    """
    Save a current raw/background pair with matching revisions in another series.
    """
    group = root / 'control' / name
    folder = group / f'{name}_s1'
    folder.mkdir(parents=True)
    original = group / f'{name}.tif'
    shutil.copy2(template.original_image, original)
    reader = ScopeIO.from_path(original)
    raw = folder / cst.FITS_ARRAY_RAW
    metadata = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_RAW,
                                    channel_labels=['Red'], custom_metadata={'pipeline_meta': {'version': '4.0.0'}}).new_revision()
    reader.save_array(np.ones((8, 8), dtype=np.float32), metadata=metadata, output_path=raw)
    state = ExperimentState.init(folder, original, run_dir=root).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=raw)
    bg = folder / cst.FITS_ARRAY_BGSUB
    reader.save_array(np.ones((8, 8), dtype=np.float32), output_path=bg,
                      metadata=metadata.with_artifact(artifact_type=cst.ARTI_IMG_BGSUB).new_revision([
                          {'artifact_path': raw.name, 'created_at': metadata.artifact.created_at}]))
    return save_experiment_state(state.with_complete_step(step_name=cst.StepName.BG_SUB,
                                                         artifact_kind=cst.ARTI_IMG_BGSUB, artifact_path=bg))


def test_required_rebuild_combines_scopes_and_leaves_healthy_series(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fully reconstruct migrated results, update stale downstream work, and preserve healthy experiments.
    """
    adapter, _, _ = legacy_run(tmp_path, masks=True)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    migrated = api.migrate(migration)[0]
    stale = _current_series(migrated, 'image_s2', tmp_path)
    healthy = _current_series(migrated, 'image_s3', tmp_path)
    raw = stale.workdir / cst.FITS_ARRAY_RAW
    rewrite_metadata(raw, read_metadata(raw).new_revision())
    before = {path: path.read_bytes() for path in healthy.workdir.iterdir() if path.is_file()}
    mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    plan = api.plan_required_rebuild(tmp_path)
    assert plan is not None
    assert plan.full_rebuild_series == (migrated.workdir,)
    assert plan.scope[stale.workdir] == (cst.StepName.BG_SUB,)
    assert healthy.workdir not in plan.scope
    assert cst.StepName.CONVERT in plan.scope[migrated.workdir]
    api.update_downstream(plan, lambda selected: start_pipeline(adapter.save_to_run_dir(),
                                                               maintenance=selected, terminal_progress=False))
    assert all(path.read_bytes() == value for path, value in before.items())
    states = discover_saved_states(tmp_path)
    assert all(state.migration_checkpoint is None for state in states)
    assert not inspect_run(tmp_path, adapter.as_mapping(), for_execution=False).conflicts
    assert api.plan_required_rebuild(tmp_path) is None


def test_compacted_experiment_requires_full_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Reconstruct a genuinely compacted workflow and replace final outputs with valid stage files.
    """
    adapter, _, _ = legacy_run(tmp_path)
    mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    api.migrate(migration)

    def run(plan: api.ProcessingPlan) -> None:
        """
        Execute the reviewed reconstruction through the ordinary pipeline.
        """
        start_pipeline(adapter.save_to_run_dir(), maintenance=plan, terminal_progress=False)

    initial = api.plan_required_rebuild(tmp_path)
    assert initial is not None
    api.update_downstream(initial, run)
    api.apply_compaction(api.plan_compaction(tmp_path))
    state = discover_saved_states(tmp_path)[0]
    assert state.compacted
    assert not (state.workdir / cst.FITS_ARRAY_RAW).exists()
    assert (state.workdir / cst.FITS_ARRAY_NAME).is_file()
    plan = api.plan_required_rebuild(tmp_path)
    assert plan is not None
    assert plan.fully_rebuilds(state.workdir)
    assert cst.StepName.CONVERT in plan.scope[state.workdir]
    api.update_downstream(plan, run)
    current = discover_saved_states(tmp_path)[0]
    assert not current.compacted
    assert (current.workdir / cst.FITS_ARRAY_RAW).is_file()
    assert (current.workdir / cst.FITS_ARRAY_BGSUB).is_file()
    assert not (current.workdir / cst.FITS_ARRAY_NAME).exists()
    assert api.plan_required_rebuild(tmp_path) is None


def test_removed_experiments_can_refresh_an_orphan_master(tmp_path: Path) -> None:
    """
    Clear a master whose last experiment was removed, retaining a restorable backup.
    """
    legacy_run(tmp_path, masks=True)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    state = api.migrate(migration)[0]
    master = tmp_path / cst.MASTER_QUANTI_NAME
    assert master.is_file()
    shutil.rmtree(state.original_image.parent)
    assert not discover_saved_states(tmp_path)
    assert inspect_locations(tmp_path).needs_update
    plan = api.plan_update(tmp_path)
    assert plan is not None
    api.update(plan)
    assert not master.exists()
    assert not inspect_locations(tmp_path).needs_update
