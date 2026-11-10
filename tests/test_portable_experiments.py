from pathlib import Path
import shutil
import numpy as np
import pytest
import tifffile
from scope_io import ScopeIO
from fits.environment import constant as cst
from fits.environment.paths import experiment_state_path, experiment_cache
from fits.gui.settings import SettingsAdapter
from fits.pipeline import start_pipeline
from fits.workflows.experiments import discover_saved_states
from fits.tasks.analysis.aggregate import _condition_values


def prepared(tmp_path):
    folder = tmp_path / 'control'
    folder.mkdir()
    original = folder / 'image.tif'
    tifffile.imwrite(original, np.arange(64, dtype=np.uint16).reshape(8, 8), photometric='minisblack')
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_runtime_value('execution', 'batch')
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', ['Red'])
    start_pipeline(adapter.save_to_run_dir(), terminal_progress=False)
    return adapter, discover_saved_states(tmp_path)[0]


def test_conversion_group_and_move_are_portable(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    adapter, state = prepared(run)
    assert state.workdir == run / 'control/image/image_s1'
    assert state.original_image == run / 'control/image/image.tif'
    assert experiment_state_path(state.workdir).is_file()
    assert not (state.workdir / 'experiment_state.json').exists()
    assert state.analysis_experiment_id == 'control/image/image_s1'
    assert _condition_values(state, run) == ('control',)
    moved = tmp_path / 'moved'
    shutil.move(run, moved)
    restored = discover_saved_states(moved)[0]
    assert restored.original_image.is_file()
    assert restored.artifact(cst.ARTI_IMG_RAW).is_file()
    assert restored.analysis_experiment_id == state.analysis_experiment_id
    assert experiment_cache(restored.workdir) == moved / 'control/image/.fits_experiment/cache/image_s1'


def test_grouping_is_idempotent_and_collision_keeps_source(tmp_path):
    from fits.workflows.experiments.acquisitions import group_acquisition
    source = tmp_path / 'image.nd2'
    source.write_bytes(b'original')
    grouped = group_acquisition(source)
    assert group_acquisition(grouped) == grouped
    source.write_bytes(b'other')
    with pytest.raises(ValueError, match='already exists'):
        group_acquisition(source)
    assert source.read_bytes() == b'other'
    assert grouped.read_bytes() == b'original'


def test_run_root_and_mixed_status(tmp_path):
    from fits.workflows.experiments.roots import resolve_run_root
    from fits.workflows.checks.compatibility import inspect_run_compatibility, require_current_run
    adapter, state = prepared(tmp_path)
    assert resolve_run_root(state.workdir) == tmp_path
    assert resolve_run_root(state.workdir.parent) == tmp_path
    assert not inspect_run_compatibility(tmp_path).outdated
    old = tmp_path / 'legacy_series'
    old.mkdir()
    tifffile.imwrite(old / cst.FITS_ARRAY_NAME, np.ones((8, 8), dtype=np.uint16))
    assert inspect_run_compatibility(tmp_path).outdated
    with pytest.raises(ValueError, match='entire run is outdated/read-only'):
        require_current_run(tmp_path)
    # Metadata history must not contaminate the active run's status.
    old.rename(state.original_image.parent / '.fits_experiment' / 'legacy' )
    assert not inspect_run_compatibility(tmp_path).outdated


def test_fresh_and_orphan_selection(tmp_path):
    from fits.workflows.experiments.roots import resolve_run_root
    fresh = tmp_path / 'fresh'
    fresh.mkdir()
    (fresh / 'input.nd2').touch()
    assert resolve_run_root(fresh) == fresh
    orphan = tmp_path / 'orphan'
    orphan.mkdir()
    (orphan / cst.FITS_ARRAY_RAW).touch()
    with pytest.raises(ValueError, match='detached'):
        resolve_run_root(orphan)


def old_layout(root):
    import json
    import pandas as pd
    from fits.workflows.experiments import ExperimentState
    from fits.workflows.experiments.serialization import serialize_experiment_state
    from fits.tasks.common.table_results import save_parquet
    folder = root / 'control'
    folder.mkdir()
    source = folder / 'image.tif'
    pixels = np.arange(64, dtype=np.uint16).reshape(8, 8)
    tifffile.imwrite(source, pixels, photometric='minisblack')
    workdir = folder / 'image_s1'
    workdir.mkdir()
    reader = ScopeIO.from_path(source)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_RAW,
        custom_metadata={'pipeline_meta': {'version': '4.0.0'}}).new_revision([
            {'artifact_path': '../image.tif', 'external': True, 'created_at': None}])
    raw = reader.save_array(pixels, metadata=payload, output_path=workdir / cst.FITS_ARRAY_RAW)
    state = ExperimentState.init(workdir, source, run_dir=root).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=raw)
    table = workdir / cst.FITS_QUANTI_NAME
    save_parquet(pd.DataFrame({'object_name': ['tracking'], 'object_channel': ['Red'],
        'label': [1], 'frame': [1], 'intensity_mean': [123.25]}), table,
        payload.with_artifact(artifact_type=cst.ARTI_QUANTI).new_revision([
            {'artifact_path': raw.name, 'created_at': payload.artifact.created_at}]))
    state = state.with_complete_step(step_name=cst.StepName.EXTRACT,
        artifact_kind=cst.ARTI_QUANTI, artifact_path=table)
    (workdir / 'experiment_state.json').write_text(json.dumps(serialize_experiment_state(state)))
    return state


def test_layout_upgrade_and_tag_refresh_preserve_measurements(tmp_path):
    import pandas as pd
    from fits.workflows.file_management.relocation import plan_portable_update, apply_portable_update
    from fits.workflows.checks.compatibility import inspect_run_compatibility
    old = old_layout(tmp_path)
    plan = plan_portable_update(tmp_path, upgrade=True)
    assert not plan.rebuild
    states = apply_portable_update(plan)
    state = states[0]
    assert state.original_image.is_file()
    assert not inspect_run_compatibility(tmp_path).outdated
    table = pd.read_parquet(state.artifact(cst.ARTI_QUANTI))
    assert table['intensity_mean'].tolist() == [123.25]
    assert table['experiment_id'].tolist() == ['image/image_s1']
    assert 'condition_level_1' not in table
    moved = tmp_path / 'treated' / 'image'
    moved.parent.mkdir()
    shutil.move(state.original_image.parent, moved)
    refresh = plan_portable_update(tmp_path, selected=moved)
    apply_portable_update(refresh)
    table = pd.read_parquet(moved / 'image_s1' / cst.FITS_QUANTI_NAME)
    assert table['intensity_mean'].tolist() == [123.25]
    assert table['experiment_id'].tolist() == ['image/image_s1']
    assert 'condition_level_1' not in table


def test_layout_failure_rolls_back_moves_and_state(tmp_path, monkeypatch):
    from fits.workflows.file_management.relocation import plan_portable_update, apply_portable_update
    import fits.workflows.file_management.relocation as portable
    old = old_layout(tmp_path)
    source = old.original_image
    state_bytes = (old.workdir / 'experiment_state.json').read_bytes()
    plan = plan_portable_update(tmp_path, upgrade=True)
    monkeypatch.setattr(portable, '_refresh_table', lambda *args: (_ for _ in ()).throw(OSError('simulated failure')))
    with pytest.raises(OSError, match='simulated'):
        apply_portable_update(plan)
    assert source.is_file()
    assert (old.workdir / 'experiment_state.json').read_bytes() == state_bytes
    assert old.artifact(cst.ARTI_IMG_RAW).is_file()


def test_history_restore_delete_and_compact_hint(tmp_path):
    from fits.workflows.file_management.relocation import plan_portable_update, apply_portable_update
    from fits.workflows.file_management.history import snapshots, restore_history, delete_history
    from fits.workflows.file_management.snapshots import preserve_replaced_results
    from fits.workflows.checks.models import ArtifactRecord, PreflightReport
    from fits.workflows.artifacts.provenance import read_metadata
    from fits.workflows.file_management.compaction import plan_compaction
    adapter, state = prepared(tmp_path)
    image = state.artifact(cst.ARTI_IMG_RAW)
    old_stamp = read_metadata(image).artifact.created_at
    report = PreflightReport((ArtifactRecord(image, cst.StepName.CONVERT, read_metadata(image), legacy=True),), (), (), (state,))
    preserve_replaced_results(report)
    reader = ScopeIO.from_path(state.original_image)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_RAW,
        custom_metadata={'pipeline_meta': {'version': '4.0.0'}}).new_revision()
    reader.save_array(np.zeros((8, 8), dtype=np.uint16), metadata=payload, output_path=image)
    entries = snapshots(tmp_path)
    assert len(entries) == 1
    assert plan_compaction(tmp_path).backup_bytes > 0
    restored = restore_history(tmp_path, entries[0])
    assert restored is not None
    assert read_metadata(restored.artifact(cst.ARTI_IMG_RAW)).artifact.created_at == old_stamp
    entries = snapshots(tmp_path)
    assert entries
    active = image.read_bytes()
    delete_history(tmp_path, entries)
    assert image.read_bytes() == active
    assert not snapshots(tmp_path)
    assert 'Manage files' not in plan_compaction(tmp_path).describe()


def test_upgrade_rebuild_is_explicit_and_cancellation_stays_read_only(tmp_path):
    import json
    from dataclasses import replace
    from fits.workflows.file_management.relocation import plan_portable_update, apply_portable_update
    from fits.workflows.file_management.rebuild import finish_upgrade
    from fits.workflows.checks.compatibility import inspect_run_compatibility
    from fits.workflows.experiments.serialization import serialize_experiment_state
    from fits.workflows.runtime.errors import PipelineCancelled
    from scope_io.writers.metadata_update import rewrite_metadata
    old = old_layout(tmp_path)
    old.artifact(cst.ARTI_QUANTI).unlink()
    old = replace(old, artifacts={key: value for key, value in old.artifacts.items() if key != cst.ARTI_QUANTI},
                  completed_steps=(cst.StepName.CONVERT,))
    (old.workdir / 'experiment_state.json').write_text(json.dumps(serialize_experiment_state(old)))
    raw = old.artifact(cst.ARTI_IMG_RAW)
    from fits.workflows.artifacts.provenance import read_metadata
    rewrite_metadata(raw, read_metadata(raw).with_custom_metadata({'pipeline_meta': {'version': '3.3.0'}}))
    plan = plan_portable_update(tmp_path, upgrade=True)
    assert plan.rebuild
    apply_portable_update(plan)
    with pytest.raises(PipelineCancelled):
        finish_upgrade(plan, lambda: (_ for _ in ()).throw(PipelineCancelled('cancelled')))
    assert inspect_run_compatibility(tmp_path).outdated
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_runtime_value('execution', 'batch')
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', ['Red'])
    settings = adapter.save_to_run_dir()
    finish_upgrade(plan, lambda: start_pipeline(settings, upgrading=True, terminal_progress=False,
                                                artifact_decision=lambda report: 'rebuild'))
    assert not inspect_run_compatibility(tmp_path).outdated


def test_two_series_share_original_and_metadata_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep multiseries outputs bound to one original acquisition and metadata owner.
    """
    import importlib
    module = importlib.import_module('fits.tasks.convert')
    from_path = ScopeIO.from_path
    alt = tmp_path / '.fits' / 'second.tif'
    alt.parent.mkdir()
    tifffile.imwrite(alt, np.full((8, 8), 99, dtype=np.uint16), photometric='minisblack')
    class TwoSeries:
        def __init__(self, path: Path) -> None:
            """
            Expose source metadata as well as the synthetic series split.
            """
            self.first = from_path(path)
            self.reader = self.first.reader
        def resolve_channel_selection(self, **kwargs):
            return self.first.resolve_channel_selection(**kwargs)
        def split_series(self):
            return [self.first, from_path(alt)]
    def read(path):
        if Path(path).name == 'image.tif':
            return TwoSeries(path)
        return from_path(path)
    monkeypatch.setattr(module.ScopeIO, 'from_path', read)
    adapter, first = prepared(tmp_path)
    states = discover_saved_states(tmp_path)
    assert {state.workdir.name for state in states} == {'image_s1', 'image_s2'}
    assert len({state.original_image for state in states}) == 1
    second = next(state for state in states if state.workdir.name == 'image_s2')
    image = second.artifact(cst.ARTI_IMG_RAW)
    assert image is not None
    np.testing.assert_array_equal(from_path(image).get_array().array, np.full((8, 8), 99))
    assert experiment_state_path(first.workdir).parents[2] == experiment_state_path(second.workdir).parents[2]


def test_mixed_upgrade_does_not_rebuild_current_acquisition(tmp_path):
    import json
    from dataclasses import replace
    from fits.workflows.experiments.serialization import serialize_experiment_state
    from fits.workflows.file_management.relocation import plan_portable_update, apply_portable_update
    from fits.workflows.file_management.rebuild import finish_upgrade
    from fits.workflows.artifacts.provenance import read_metadata
    from scope_io.writers.metadata_update import rewrite_metadata
    adapter, current = prepared(tmp_path)
    current_image = current.artifact(cst.ARTI_IMG_RAW)
    stamp = read_metadata(current_image).artifact.created_at
    before = current_image.read_bytes()
    legacy_root = tmp_path / 'imported'
    legacy_root.mkdir()
    old = old_layout(legacy_root)
    old.artifact(cst.ARTI_QUANTI).unlink()
    old = replace(old, artifacts={key: value for key, value in old.artifacts.items() if key != cst.ARTI_QUANTI}, completed_steps=(cst.StepName.CONVERT,))
    (old.workdir / 'experiment_state.json').write_text(json.dumps(serialize_experiment_state(old)))
    image = old.artifact(cst.ARTI_IMG_RAW)
    rewrite_metadata(image, read_metadata(image).with_custom_metadata({'pipeline_meta': {'version': '3.3.0'}}))
    plan = plan_portable_update(tmp_path, upgrade=True)
    assert len(plan.rebuild_series) == 1
    assert current.workdir not in plan.rebuild_series
    apply_portable_update(plan)
    finish_upgrade(plan, lambda: start_pipeline(adapter.save_to_run_dir(), upgrading=True,
                                               artifact_decision=lambda report: 'rebuild', terminal_progress=False))
    assert current_image.read_bytes() == before
    assert read_metadata(current_image).artifact.created_at == stamp


def test_explicit_branch_alignment_review_keeps_drawing_pixels(tmp_path):
    from fits.workflows.file_management.rebuild import geometry_reviews, accept_reviewed_geometry
    from fits.workflows.artifacts.branch_masks import geometry
    from fits.workflows.artifacts.provenance import read_metadata
    from scope_io.writers.metadata_update import rewrite_metadata
    adapter, state = prepared(tmp_path)
    image = state.artifact(cst.ARTI_IMG_RAW)
    rewrite_metadata(image, read_metadata(image).with_custom_metadata({'registration_revisions': {'register_channel': 'old'}}))
    reader = ScopeIO.from_path(image)
    ref = reader.save_array(np.ones((8, 8), dtype=np.uint16), artifact_kind=cst.ARTI_REF,
                            output_path=state.workdir / 'fits_ref_edge.tif', export_channels='all')
    pixels = ScopeIO.from_path(ref).get_array().array.copy()
    stamp = read_metadata(ref).artifact.created_at
    rewrite_metadata(image, read_metadata(image).with_custom_metadata({'registration_revisions': {'register_channel': 'new'}}))
    reviews = geometry_reviews(tmp_path)
    assert reviews == ((ref, image),)
    accept_reviewed_geometry(tmp_path, reviews)
    assert not geometry_reviews(tmp_path)
    assert geometry(read_metadata(ref)) == geometry(read_metadata(image))
    assert read_metadata(ref).artifact.created_at == stamp
    np.testing.assert_array_equal(ScopeIO.from_path(ref).get_array().array, pixels)
