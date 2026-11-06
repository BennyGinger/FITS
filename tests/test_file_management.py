"""Real-file migration and independent file-management actions."""
import json
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import tifffile
from numpy.typing import NDArray
from fits_io import FitsIO
from fits.environment import constant as cst
from fits.gui.settings import SettingsAdapter
from fits.workflows.experiments import ExperimentState, discover_saved_states
from fits.workflows.experiments.serialization import serialize_experiment_state
from fits.workflows.file_management.api import plan_migration, migrate
from fits.workflows.artifacts.provenance import read_metadata, compatible


def legacy_run(root: Path, *, masks: bool = False, frames: int = 1, channels: int = 1) -> tuple[SettingsAdapter, ExperimentState, NDArray[np.uint16]]:
    """
    Build legacy outputs with optional time and channel dimensions for rebuild checks.
    """
    folder = root / 'control'
    folder.mkdir()
    original = folder / 'image.tif'
    shape = ((frames,) if frames > 1 else ()) + ((channels,) if channels > 1 else ()) + (8, 8)
    axes = ('T' if frames > 1 else '') + ('C' if channels > 1 else '') + 'YX'
    labels = ['Red', 'Green'][:channels]
    pixels = np.arange(np.prod(shape), dtype=np.uint16).reshape(shape)
    tifffile.imwrite(original, pixels, photometric='minisblack', metadata={'axes': axes})
    series = folder / 'image_s1'
    series.mkdir()
    reader = FitsIO.from_path(original)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG,
        channel_labels=labels, custom_metadata={'pipeline_meta': {'version': '3.3.0'},
        'steps': {}})
    image = reader.save_array(pixels, metadata=payload, output_path=series / cst.FITS_ARRAY_NAME)
    state = ExperimentState.init(series, original, run_dir=root).with_complete_step(
        step_name=cst.StepName.BG_SUB, artifact_kind=cst.ARTI_IMG, artifact_path=image)
    state = replace(state, completed_steps=('convert', 'bg_sub'))
    if masks:
        seg = reader.save_array(np.ones_like(pixels), metadata=payload.with_fitsio(artifact_type=cst.ARTI_SEG),
            output_path=series / 'fits_mask.tif')
        state = state.with_complete_step(step_name=cst.StepName.SEGMENT, artifact_kind=cst.ARTI_SEG, artifact_path=seg)
        table = series / cst.FITS_QUANTI_NAME
        pd.DataFrame({'object_name': ['segmentation'], 'object_channel': ['Red'], 'label': [1],
            'frame': [1], 'intensity_mean': [123.25]}).to_parquet(table, index=False)
        state = state.with_complete_step(step_name=cst.StepName.EXTRACT, artifact_kind=cst.ARTI_QUANTI, artifact_path=table)
    (series / 'experiment_state.json').write_text(json.dumps(serialize_experiment_state(state)))
    adapter = SettingsAdapter()
    adapter.run_dir = str(root)
    adapter.user_name = 'Test'
    adapter.set_runtime_value('execution', 'batch')
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', labels)
    adapter.set_step_enabled(cst.StepName.BG_SUB, True)
    adapter.save_to_run_dir()
    return adapter, state, pixels


def mock_rebuild_processing(monkeypatch: pytest.MonkeyPatch, adapter: SettingsAdapter) -> list[str]:
    """
    Exercise real metadata/state publication without loading segmentation or tracking backends.
    """
    from typing import Any
    from fits.workflows.definitions.models import StepProfile
    from fits.workflows.definitions.registry import REGISTRY
    from fits.tasks.common.preparation import load_input_reader
    from fits.tasks.common.artifact_results import save_step_result, complete_step_result
    from fits.tasks.common.table_results import save_parquet
    from fits.workflows.artifacts.provenance import revision_payload

    calls: list[str] = []
    adapter.set_segment_channels([{'channel': 'Red'}])

    def array_step(settings: Any, state: ExperimentState, profile: StepProfile) -> list[ExperimentState]:
        """
        Write deliberately changed outputs with genuine references to their new inputs.
        """
        calls.append(str(profile.step_name))
        reader = load_input_reader(state, profile)
        pixels = reader.get_array().array
        values = (np.ones_like(pixels, dtype=np.uint16) if profile.step_name in (cst.StepName.SEGMENT, cst.StepName.TRACK)
                  else pixels.astype(np.float32) + 1)
        updated = state.with_metadata(step_name=profile.step_name, created_by=profile.distribution)
        return [save_step_result(reader, values, list(reader.channel_labels), updated, profile)]

    def extract(settings: Any, state: ExperimentState, profile: StepProfile) -> list[ExperimentState]:
        """
        Publish a replacement measurement table with the actual rebuilt dependencies.
        """
        calls.append(str(profile.step_name))
        reader = load_input_reader(state, profile)
        frame = pd.DataFrame({'object_name': ['segmentation'], 'object_channel': ['Red'], 'label': [1],
                              'frame': [1], 'intensity_mean': [float(reader.get_array().array.mean())]})
        updated = state.with_metadata(step_name=profile.step_name, created_by=profile.distribution)
        payload = revision_payload(reader, updated, profile, export_channels=list(reader.channel_labels))
        path = save_parquet(frame, state.workdir / profile.output_name, payload)
        return [complete_step_result(updated, profile, path)]

    for step in (cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME, cst.StepName.BG_SUB,
                 cst.StepName.SEGMENT, cst.StepName.TRACK):
        monkeypatch.setitem(REGISTRY, step, replace(REGISTRY[step], item_runner=array_step))
    monkeypatch.setitem(REGISTRY, cst.StepName.EXTRACT, replace(REGISTRY[cst.StepName.EXTRACT], item_runner=extract))
    return calls


def test_migrate_preserves_legacy_pixels_measurements_and_producer_history(tmp_path):
    from fits.workflows.checks.compatibility import inspect_run_compatibility
    from fits.workflows.checks.artifacts import inspect_run
    adapter, old, pixels = legacy_run(tmp_path, masks=True)
    plan = plan_migration(tmp_path)
    assert plan.migrate and not plan.rebuild
    state = migrate(plan)[0]
    assert state.migration_checkpoint == 'bg_sub'
    assert state.artifact(cst.ARTI_IMG_BGSUB).name == cst.FITS_ARRAY_BGSUB
    assert state.artifact(cst.ARTI_IMG_RAW) is None
    np.testing.assert_array_equal(FitsIO.from_path(state.artifact(cst.ARTI_IMG)).get_array().array, pixels)
    for kind in (cst.ARTI_IMG, cst.ARTI_SEG, cst.ARTI_QUANTI):
        payload = read_metadata(state.artifact(kind))
        assert compatible(payload)
        if kind != cst.ARTI_QUANTI:
            assert payload.custom_metadata['migration']['original_pipeline_meta']['version'] == '3.3.0'
    table = pd.read_parquet(state.artifact(cst.ARTI_QUANTI))
    assert table['intensity_mean'].tolist() == [123.25]
    assert table['experiment_id'].tolist() == ['image/image_s1']
    assert not inspect_run_compatibility(tmp_path).outdated
    assert not inspect_run(tmp_path, adapter.as_mapping()).conflicts
    assert plan_migration(tmp_path) is None


def test_migrated_preprocess_can_build_segmentation_without_rebuilding(tmp_path, monkeypatch):
    from fits.pipeline import start_pipeline
    from fits.workflows.definitions.registry import REGISTRY
    from fits.tasks.common.preparation import load_input_reader
    from fits.tasks.common.artifact_results import save_step_result
    adapter, old, pixels = legacy_run(tmp_path)
    state = migrate(plan_migration(tmp_path))[0]
    before = state.artifact(cst.ARTI_IMG).read_bytes()
    calls = []
    def segment(settings, state, profile):
        reader = load_input_reader(state, profile)
        np.testing.assert_array_equal(reader.get_array().array, pixels)
        calls.append(state.workdir)
        return [save_step_result(reader, np.ones((8, 8), dtype=np.uint16), ['Red'], state, profile)]
    monkeypatch.setitem(REGISTRY, cst.StepName.SEGMENT, replace(REGISTRY[cst.StepName.SEGMENT], item_runner=segment))
    adapter.set_step_enabled(cst.StepName.SEGMENT, True)
    adapter.set_segment_channels([{'channel': 'Red'}])
    start_pipeline(adapter.save_to_run_dir(), terminal_progress=False)
    current = discover_saved_states(tmp_path)[0]
    assert calls == [state.workdir]
    assert current.artifact(cst.ARTI_SEG).is_file()
    assert current.artifact(cst.ARTI_IMG).read_bytes() == before
    assert not read_metadata(current.artifact(cst.ARTI_SEG)).custom_metadata.get('migration')


def test_optional_full_rebuild_replaces_final_results_with_consistent_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Rebuild registration, final arrays, masks and measurements instead of accepting old finals.
    """
    from fits.workflows.file_management.api import plan_full_rebuild, update_downstream
    from fits.workflows.file_management.history import snapshots
    from fits.workflows.checks.artifacts import inspect_run
    from fits.settings.loader import load_settings
    from fits.pipeline import start_pipeline
    adapter, old, pixels = legacy_run(tmp_path, masks=True, frames=2, channels=2)
    old = replace(old, completed_steps=('convert', 'register_channel', 'register_time', 'bg_sub', 'segment', 'extract'))
    (old.workdir / 'experiment_state.json').write_text(json.dumps(serialize_experiment_state(old)))
    calls = mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    state = migrate(plan_migration(tmp_path))[0]
    originals = {state.artifact(kind): state.artifact(kind).read_bytes()
                 for kind in (cst.ARTI_IMG, cst.ARTI_SEG, cst.ARTI_QUANTI)}
    plan = plan_full_rebuild(tmp_path)
    assert plan is not None
    assert plan.scope[state.workdir] == ('convert', 'register_channel', 'register_time', 'bg_sub', 'segment', 'extract')
    assert 'can take a long time' in plan.describe() and 'backed up before' in plan.describe()
    update_downstream(plan, lambda reviewed: start_pipeline(adapter.save_to_run_dir(), maintenance=reviewed, terminal_progress=False))
    current = discover_saved_states(tmp_path)[0]
    assert current.migration_checkpoint is None
    assert calls == ['register_channel', 'register_time', 'bg_sub', 'segment', 'extract']
    from fits.workflows.definitions.registry import REGISTRY
    for step in plan.scope[state.workdir]:
        assert (current.workdir / REGISTRY[step].profile.output_name).is_file()
    np.testing.assert_array_equal(FitsIO.from_path(current.artifact(cst.ARTI_IMG)).get_array().array, pixels + 3)
    assert pd.read_parquet(current.artifact(cst.ARTI_QUANTI))['intensity_mean'][0] != 123.25
    assert not (current.workdir / 'fits_mask.tif').exists()
    assert not read_metadata(current.artifact(cst.ARTI_IMG)).custom_metadata.get('migration')
    assert not inspect_run(tmp_path, load_settings(adapter.source_path), for_execution=False).conflicts
    backup = next(entry for entry in snapshots(tmp_path) if not entry.whole_run)
    for path, contents in originals.items():
        assert (backup.directory / path.name).read_bytes() == contents


def test_downstream_update_preserves_upstream_and_other_series(tmp_path, monkeypatch):
    import importlib
    import shutil
    from fits.workflows.experiments import save_experiment_state
    from fits.workflows.file_management.api import plan_downstream_update, update_downstream
    from fits.workflows.checks.artifacts import inspect_run
    from fits.pipeline import start_pipeline
    from fits_io.writers.metadata_update import rewrite_metadata
    adapter, old, pixels = legacy_run(tmp_path)
    state = migrate(plan_migration(tmp_path))[0]
    reader = FitsIO.from_path(state.original_image)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_RAW,
        channel_labels=['Red'], custom_metadata={'pipeline_meta': {'version': '4.0.0'}}).new_revision()
    raw = reader.save_array(pixels, metadata=payload, output_path=state.workdir / cst.FITS_ARRAY_RAW)
    bg = reader.save_array(pixels.astype(np.float32), metadata=payload.with_fitsio(artifact_type=cst.ARTI_IMG_BGSUB).new_revision([
        {'artifact_path': raw.name, 'created_at': payload.fits_io.created_at}]), output_path=state.workdir / cst.FITS_ARRAY_BGSUB)
    state = state.with_complete_step(step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=raw)
    state = state.with_complete_step(step_name=cst.StepName.BG_SUB, artifact_kind=cst.ARTI_IMG_BGSUB, artifact_path=bg)
    save_experiment_state(state)
    other = state.workdir.parent / 'image_s2'
    other.mkdir()
    for path in (raw, bg):
        shutil.copy2(path, other / path.name)
    sibling = replace(state, workdir=other)
    save_experiment_state(sibling)
    untouched = {path: path.read_bytes() for path in other.glob('*.tif')}
    rewrite_metadata(raw, read_metadata(raw).new_revision())
    raw_bytes = raw.read_bytes()
    plan = plan_downstream_update(tmp_path)
    assert plan.scope == {state.workdir: ('bg_sub',)}
    monkeypatch.setattr(importlib.import_module('fits.tasks.bg_sub'), 'bg_sub', lambda array, **kw: array.astype(np.float32) + .5)
    update_downstream(plan, lambda plan: start_pipeline(adapter.save_to_run_dir(), maintenance=plan, terminal_progress=False))
    assert raw.read_bytes() == raw_bytes
    assert all(path.read_bytes() == data for path, data in untouched.items())
    assert not inspect_run(tmp_path, adapter.as_mapping(), for_execution=False).conflicts
    assert plan_downstream_update(tmp_path) is None


def test_migration_rollback_restores_original_files_and_layout(tmp_path, monkeypatch):
    import fits.workflows.file_management.relocation as portable
    adapter, state, pixels = legacy_run(tmp_path, masks=True)
    originals = {path: path.read_bytes() for path in state.workdir.iterdir() if path.is_file()}
    plan = plan_migration(tmp_path)
    def fail(*args):
        raise OSError('injected table failure')
    monkeypatch.setattr(portable, '_refresh_table', fail)
    with pytest.raises(OSError, match='injected'):
        migrate(plan)
    assert state.original_image.is_file()
    assert all(path.read_bytes() == data for path, data in originals.items())
    assert not (tmp_path / 'control/image/image.tif').exists()


def test_migrated_masks_notice_new_processing_inputs(tmp_path):
    from fits.workflows.experiments import save_experiment_state
    from fits.workflows.checks.artifacts import inspect_run
    adapter, old, pixels = legacy_run(tmp_path, masks=True)
    state = migrate(plan_migration(tmp_path))[0]
    old_image = state.artifact(cst.ARTI_IMG)
    reader = FitsIO.from_path(old_image)
    # New processing writes a distinct artifact; the accepted old mask still
    # references the old canonical image and must become stale.
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_BGSUB).new_revision()
    current = reader.save_array(pixels.astype(np.float32), metadata=payload,
        output_path=state.workdir / cst.FITS_ARRAY_BGSUB)
    state = state.with_complete_step(step_name=cst.StepName.BG_SUB, artifact_kind=cst.ARTI_IMG_BGSUB, artifact_path=current)
    save_experiment_state(state)
    report = inspect_run(tmp_path, adapter.as_mapping(), for_execution=False)
    assert any(record.path == state.artifact(cst.ARTI_SEG) and record.problem for record in report.conflicts)


def test_migrated_final_can_be_compacted_without_reprocessing(tmp_path):
    from fits.workflows.file_management.compaction import compact_run
    adapter, old, pixels = legacy_run(tmp_path, masks=True)
    state = migrate(plan_migration(tmp_path))[0]
    stamp = read_metadata(state.artifact(cst.ARTI_IMG)).fits_io.created_at
    compact_run(tmp_path, choose=lambda report: 'continue', confirm=lambda plan: True)
    compacted = discover_saved_states(tmp_path)[0]
    assert compacted.compacted
    assert read_metadata(compacted.artifact(cst.ARTI_IMG)).fits_io.created_at == stamp
    np.testing.assert_array_equal(FitsIO.from_path(compacted.artifact(cst.ARTI_IMG)).get_array().array, pixels)
    assert compacted.artifact(cst.ARTI_SEG).name == cst.FITS_MASKS_COMPACTED


def test_full_rebuild_merges_all_series_from_one_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    from fits.pipeline import start_pipeline
    from fits.workflows.experiments import save_experiment_state
    from fits.workflows.file_management.api import plan_full_rebuild, update_downstream
    adapter, old, pixels = legacy_run(tmp_path)
    mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    first = migrate(plan_migration(tmp_path))[0]
    other = first.workdir.parent / 'image_s2'
    other.mkdir()
    reader = FitsIO.from_path(first.original_image)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_RAW,
        channel_labels=['Red'], custom_metadata={'pipeline_meta': {'version': '4.0.0'}}).new_revision()
    raw = reader.save_array(np.full((8, 8), 9, dtype=np.uint16), metadata=payload,
        output_path=other / cst.FITS_ARRAY_RAW)
    sibling = ExperimentState.init(other, first.original_image, run_dir=tmp_path).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=raw)
    save_experiment_state(sibling)
    before = raw.read_bytes()
    from_path = FitsIO.from_path
    source = first.original_image
    class TwoSeries:
        def __init__(self, path: Path) -> None:
            """
            Expose the real reader metadata used by conversion preflight.
            """
            self.first = from_path(path)
            self.reader = self.first.reader
        def resolve_channel_selection(self, **kwargs):
            return self.first.resolve_channel_selection(**kwargs)
        def split_series(self):
            return [self.first, from_path(source)]
    monkeypatch.setattr(importlib.import_module('fits.tasks.convert').FitsIO, 'from_path',
        lambda path: TwoSeries(path) if Path(path) == source else from_path(path))
    plan = plan_full_rebuild(tmp_path)
    assert set(plan.scope) == {first.workdir, other}
    assert all(steps == ('convert', 'bg_sub') for steps in plan.scope.values())
    update_downstream(plan, lambda plan: start_pipeline(adapter.save_to_run_dir(), maintenance=plan, terminal_progress=False))
    assert raw.read_bytes() != before
    states = discover_saved_states(tmp_path)
    assert len(states) == 2
    current = next(state for state in states if state.workdir == first.workdir)
    assert current.artifact(cst.ARTI_IMG_RAW).is_file()
    assert current.artifact(cst.ARTI_IMG).name == cst.FITS_ARRAY_BGSUB


def test_update_rebinds_saved_run_settings_after_move(tmp_path):
    import shutil
    import tomlkit
    from fits.workflows.file_management.api import plan_update, update
    old_root = tmp_path / 'old'
    old_root.mkdir()
    adapter, old, pixels = legacy_run(old_root)
    state = migrate(plan_migration(old_root))[0]
    settings = old_root / '.fits/fits_settings.toml'
    document = tomlkit.parse(settings.read_text())
    document['optimize'] = str(state.original_image)
    settings.write_text(tomlkit.dumps(document))
    moved = tmp_path / 'moved'
    shutil.move(old_root, moved)
    update(plan_update(moved))
    document = tomlkit.parse((moved / '.fits/fits_settings.toml').read_text())
    assert document['run_dir'] == str(moved)
    assert document['optimize'] == str(moved / 'control/image/image.tif')


def test_full_rebuild_recreates_segmentation_and_tracking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fits.workflows.file_management.api import plan_full_rebuild, update_downstream
    from fits.workflows.definitions.registry import REGISTRY
    from fits.workflows.checks.artifacts import inspect_run
    from fits.tasks.common.preparation import load_input_reader
    from fits.tasks.common.artifact_results import save_step_result
    from fits.pipeline import start_pipeline
    adapter, state, pixels = legacy_run(tmp_path, frames=2)
    image = state.artifact(cst.ARTI_IMG)
    reader = FitsIO.from_path(image)
    tracking = reader.save_array(np.ones_like(pixels),
        metadata=read_metadata(image).with_fitsio(artifact_type=cst.ARTI_TRACK),
        output_path=state.workdir / 'fits_track.tif')
    state = state.with_complete_step(step_name=cst.StepName.TRACK, artifact_kind=cst.ARTI_TRACK, artifact_path=tracking)
    (state.workdir / 'experiment_state.json').write_text(json.dumps(serialize_experiment_state(state)))
    state = migrate(plan_migration(tmp_path))[0]
    assert state.artifact(cst.ARTI_SEG) is None
    assert not inspect_run(tmp_path, adapter.as_mapping(), for_execution=False).conflicts
    tracked_bytes = state.artifact(cst.ARTI_TRACK).read_bytes()
    mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    plan = plan_full_rebuild(tmp_path)
    assert plan.scope[state.workdir] == ('convert', 'bg_sub', 'segment', 'track')
    update_downstream(plan, lambda plan: start_pipeline(adapter.save_to_run_dir(), maintenance=plan, terminal_progress=False))
    current = discover_saved_states(tmp_path)[0]
    assert current.artifact(cst.ARTI_SEG).is_file()
    assert current.artifact(cst.ARTI_TRACK).read_bytes() != tracked_bytes
    assert not inspect_run(tmp_path, adapter.as_mapping(), for_execution=False).conflicts


def _active_run_bytes(root: Path) -> dict[Path, bytes]:
    """
    Capture active files without retained history or the runtime write lock.
    """
    return {path.relative_to(root): path.read_bytes() for path in root.rglob('*')
            if path.is_file() and not path.is_relative_to(root / '.fits/backup')
            and path != root / '.fits/run_write.lock'}


def test_migration_history_restores_original_layout_and_bytes(tmp_path: Path) -> None:
    """
    Restore pre-v4 files exactly, then recover the retained migrated run as well.
    """
    import shutil
    from fits.workflows.file_management.history import snapshots, restore_history
    from fits.workflows.checks.compatibility import inspect_run_compatibility
    from fits.workflows.experiments import discover_saved_states

    _, old, _ = legacy_run(tmp_path, masks=True)
    sibling = old.workdir.with_name('image_s2')
    shutil.copytree(old.workdir, sibling)
    (old.workdir / 'notes.txt').write_text('Keep this original file too.')
    pd.DataFrame({'old_measurement': [12.5]}).to_parquet(tmp_path / cst.MASTER_QUANTI_NAME)
    before = _active_run_bytes(tmp_path)
    states = migrate(plan_migration(tmp_path))
    migrated = _active_run_bytes(tmp_path)
    entries = snapshots(tmp_path, states[0].workdir)
    assert len(entries) == 1 and entries[0].whole_run
    for relative, data in before.items():
        assert (entries[0].directory / 'run' / relative).read_bytes() == data
    raw = old.original_image
    retained_raw = entries[0].directory / 'run' / raw.relative_to(tmp_path)
    assert not retained_raw.samefile(states[0].original_image)
    restore_history(tmp_path, entries[0])
    assert _active_run_bytes(tmp_path) == before
    assert raw.is_file() and (old.workdir / 'experiment_state.json').is_file()
    assert read_metadata(old.artifact(cst.ARTI_IMG)).custom_metadata['pipeline_meta']['version'] == '3.3.0'
    assert inspect_run_compatibility(tmp_path).outdated
    retained = snapshots(tmp_path)
    assert len(retained) == 1 and retained[0].whole_run
    restore_history(tmp_path, retained[0])
    assert _active_run_bytes(tmp_path) == migrated
    assert len(discover_saved_states(tmp_path)) == 2
    assert not inspect_run_compatibility(tmp_path).outdated


def test_failed_migration_keeps_original_run_without_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Roll back migration and discard its unpublished folder copy on failure.
    """
    from fits.workflows.file_management.history import snapshots
    import fits.workflows.file_management.relocation as relocation

    legacy_run(tmp_path, masks=True)
    before = _active_run_bytes(tmp_path)

    def fail_refresh(*args: object) -> None:
        """
        Interrupt migration after its folder moves and metadata writes.
        """
        raise OSError('simulated migration failure')

    monkeypatch.setattr(relocation, '_refresh_table', fail_refresh)
    with pytest.raises(OSError, match='simulated migration failure'):
        migrate(plan_migration(tmp_path))
    assert _active_run_bytes(tmp_path) == before
    assert not snapshots(tmp_path)
    assert not list((tmp_path / '.fits').glob('file_update_*'))


def test_failed_run_restore_preserves_both_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Recover the migrated run and its original snapshot if restoration fails.
    """
    from fits.workflows.file_management.history import snapshots, restore_history, verify_snapshot
    import fits.workflows.file_management.run_history as run_history

    legacy_run(tmp_path, masks=True)
    migrate(plan_migration(tmp_path))
    before = _active_run_bytes(tmp_path)
    entry = snapshots(tmp_path)[0]

    def fail_publish(*args: object) -> None:
        """
        Interrupt restoration after folders have been exchanged.
        """
        raise OSError('simulated restore failure')

    monkeypatch.setattr(run_history, 'publish_run_snapshot', fail_publish)
    with pytest.raises(OSError, match='simulated restore failure'):
        restore_history(tmp_path, entry)
    assert _active_run_bytes(tmp_path) == before
    verify_snapshot(entry)
    assert len(snapshots(tmp_path)) == 1


@pytest.mark.parametrize('after_review', [False, True])
def test_migration_checks_space_before_review_and_execution(tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch,
                                                           after_review: bool,
                                                           ) -> None:
    """
    Stop without modifying the run when space is low initially or after review.
    """
    from fits.workflows.file_management.history import snapshots
    import fits.workflows.file_management.run_history as run_history

    legacy_run(tmp_path, masks=True)
    plan = plan_migration(tmp_path) if after_review else None
    before = _active_run_bytes(tmp_path)
    usage = run_history.shutil.disk_usage(tmp_path)
    monkeypatch.setattr(run_history.shutil, 'disk_usage', lambda path: usage._replace(free=0))
    with pytest.raises(ValueError, match='Not enough disk space.*Estimated space needed.*available:'):
        if after_review:
            assert plan is not None
            migrate(plan)
        else:
            plan_migration(tmp_path)
    assert _active_run_bytes(tmp_path) == before
    assert not snapshots(tmp_path)
    assert not list((tmp_path / '.fits').glob('file_update_*'))


def test_update_backup_is_not_discovered_as_active_experiment(tmp_path: Path) -> None:
    """
    Keep pre-update folders restorable without discovering their states as live work.
    """
    from fits.workflows.file_management.api import plan_update, update
    from fits.workflows.file_management.history import snapshots, restore_history
    _, _, _ = legacy_run(tmp_path, masks=True)
    state = migrate(plan_migration(tmp_path))[0]
    original = state.artifact(cst.ARTI_IMG)
    assert original is not None
    before = original.read_bytes()
    master = tmp_path / cst.MASTER_QUANTI_NAME
    frame = pd.read_parquet(master)
    frame['condition_level_1'] = 'old condition'
    frame.to_parquet(master, index=False)
    plan = plan_update(tmp_path)
    assert plan is not None
    update(plan)
    assert len(discover_saved_states(tmp_path)) == 1
    entries = snapshots(tmp_path, state.workdir)
    backup = next(entry for entry in entries if entry.reason == 'Before updating files')
    assert backup.whole_run
    restore_history(tmp_path, backup)
    assert original.read_bytes() == before
    assert len(discover_saved_states(tmp_path)) == 1


def test_pipeline_overwrite_retains_experiment_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Retain a restorable experiment folder before an ordinary overwrite run.
    """
    from fits.pipeline import start_pipeline
    from fits.workflows.file_management.history import snapshots, restore_history
    adapter, _, _ = legacy_run(tmp_path)
    mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    state = migrate(plan_migration(tmp_path))[0]
    from fits.workflows.file_management.api import plan_full_rebuild, update_downstream
    plan = plan_full_rebuild(tmp_path)
    update_downstream(plan, lambda reviewed: start_pipeline(adapter.save_to_run_dir(), maintenance=reviewed, terminal_progress=False))
    state = discover_saved_states(tmp_path)[0]
    raw = state.artifact(cst.ARTI_IMG_RAW)
    assert raw is not None
    before = raw.read_bytes()
    adapter.set_step_enabled(cst.StepName.BG_SUB, False)
    adapter.set_field_value(cst.StepName.CONVERT, 'overwrite', True)
    start_pipeline(adapter.save_to_run_dir(), artifact_decision=lambda report: 'selected', terminal_progress=False)
    entries = [entry for entry in snapshots(tmp_path) if not entry.whole_run and (entry.directory / raw.name).is_file()]
    assert len(entries) == 1
    assert (entries[0].directory / raw.name).read_bytes() == before
    restored = restore_history(tmp_path, entries[0])
    assert restored is not None and restored.artifact(cst.ARTI_IMG_RAW).read_bytes() == before


def test_previous_backup_folder_name_remains_restorable(tmp_path: Path) -> None:
    """
    Retain access to backups created before the storage-directory rename.
    """
    from fits.workflows.file_management.history import snapshots, restore_history
    _, old, _ = legacy_run(tmp_path)
    migrate(plan_migration(tmp_path))
    (tmp_path / '.fits/backup').rename(tmp_path / '.fits/legacy')
    entries = snapshots(tmp_path)
    assert len(entries) == 1 and entries[0].whole_run
    restore_history(tmp_path, entries[0])
    image = old.workdir / cst.FITS_ARRAY_NAME
    assert image.is_file()
    assert read_metadata(image).custom_metadata['pipeline_meta']['version'] == '3.3.0'
    assert (tmp_path / '.fits/backup').is_dir()


def test_failed_full_rebuild_retains_a_restorable_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep an exact pre-rebuild backup even if an intermediate step fails.
    """
    from typing import Any
    from fits.workflows.definitions.models import StepProfile
    from fits.workflows.definitions.registry import REGISTRY
    from fits.workflows.file_management.api import plan_full_rebuild, update_downstream
    from fits.workflows.file_management.history import snapshots, restore_history
    from fits.pipeline import start_pipeline
    adapter, _, _ = legacy_run(tmp_path, masks=True)
    mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    state = migrate(plan_migration(tmp_path))[0]
    original = state.artifact(cst.ARTI_IMG)
    assert original is not None
    before = original.read_bytes()
    attempts: list[str] = []

    def fail_background(settings: Any, current: ExperimentState, profile: StepProfile) -> list[ExperimentState]:
        """
        Fail numerical processing after conversion has already replaced an earlier stage.
        """
        attempts.append(str(profile.step_name))
        raise RuntimeError('simulated background failure')

    monkeypatch.setitem(REGISTRY, cst.StepName.BG_SUB, replace(REGISTRY[cst.StepName.BG_SUB], item_runner=fail_background))
    plan = plan_full_rebuild(tmp_path)
    assert plan is not None
    with pytest.raises(RuntimeError, match='simulated background failure'):
        update_downstream(plan, lambda reviewed: start_pipeline(adapter.save_to_run_dir(), maintenance=reviewed, terminal_progress=False))
    assert attempts == ['bg_sub']
    backup = next(entry for entry in snapshots(tmp_path) if not entry.whole_run)
    assert (backup.directory / original.name).read_bytes() == before
    restored = restore_history(tmp_path, backup)
    assert restored is not None
    restored_image = restored.artifact(cst.ARTI_IMG)
    assert restored_image is not None and restored_image.read_bytes() == before
