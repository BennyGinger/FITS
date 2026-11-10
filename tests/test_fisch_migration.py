"""Whole-run FITS-to-FIScH naming migration with unchanged scientific results."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import tifffile
from scope_io import ScopeIO, ImageMetadata

from fisch.environment import constant as cst, naming
from fisch.gui.settings import SettingsAdapter
from fisch.workflows.artifacts.provenance import read_metadata, compatible
from fisch.workflows.checks.compatibility import inspect_run_compatibility, require_current_run
from fisch.workflows.experiments import ExperimentState, discover_saved_states
from fisch.workflows.experiments.serialization import serialize_experiment_state
from fisch.workflows.file_management import api


def _fits4_run(root: Path, *, compacted: bool = False) -> tuple[Path, Path, np.ndarray[Any, Any]]:
    """
    Create a genuine legacy portable acquisition with FITS names and provenance.
    """
    group = root / 'control/acquisition'
    series = group / 'acquisition_s1'
    series.mkdir(parents=True)
    original = group / 'acquisition.tif'
    pixels = np.linspace(-5.5, 20.5, 64, dtype=np.float32).reshape(8, 8)
    tifffile.imwrite(original, pixels, photometric='minisblack')
    image = series / ('fits_array.tif' if compacted else 'fits_array_raw.tif')
    payload = ImageMetadata().with_artifact(artifact_type=cst.ARTI_IMG_COMPACTED if compacted else cst.ARTI_IMG_RAW,
                                            axes='YX', channel_labels=['GFP'], created_by='fits-io', version='2.2.0',
                                            source_channel_indices=[0], artifact_channel_indices=[0])
    payload = payload.with_custom_metadata({'pipeline_meta': {'version': '4.1.0', 'created_by': 'fits'},
                                            'steps': {'convert': {'step_name': 'convert', 'created_by': 'fits-io',
                                                                 'version': '2.2.0', 'params': {}, 'channels': {}}}}).new_revision()
    ScopeIO.from_path(original).save_array(pixels, metadata=payload, output_path=image)
    state = ExperimentState.init(series, original, run_dir=root).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_COMPACTED if compacted else cst.ARTI_IMG_RAW,
        artifact_path=image)
    state = replace(state, compacted=compacted)
    table_path = series / 'fits_quantification.parquet'
    table = pa.Table.from_pandas(pd.DataFrame({'experiment_id': ['saved-experiment'], 'cell_id': ['saved-cell'], 'object_name': ['segmentation'], 'object_channel': ['GFP'],
                                              'label': [1], 'frame': [0], 'intensity_mean': [17.25]}))
    table_payload = payload.with_artifact(artifact_type='quantification').new_revision([
        {'artifact_path': image.name, 'created_at': payload.artifact.created_at}]).dump()
    table_payload['fits_io'] = table_payload.pop('artifact')
    pq.write_table(table.replace_schema_metadata({b'fits_artifact': json.dumps(table_payload).encode()}), table_path)
    state = state.with_complete_step(step_name=cst.StepName.EXTRACT, artifact_kind=cst.ARTI_QUANTI, artifact_path=table_path)
    state = replace(state, compacted=compacted)
    saved = serialize_experiment_state(state)
    saved['series_path'] = series.name
    saved['meta']['pipeline_meta']['version'] = '4.1.0'
    target = group / '.fits_experiment/experiment_state' / series.name / 'experiment_state.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(saved))
    adapter = SettingsAdapter()
    adapter.run_dir = str(root)
    adapter.user_name = 'Tester'
    adapter.save(root / '.fits/fits_settings.toml')
    return original, image, pixels


def test_fits4_names_and_headers_migrate_without_changing_pixels_or_revisions(tmp_path: Path) -> None:
    """
    Rebind a portable FITS-4 acquisition, legacy table metadata and its references.
    """
    original, image, pixels = _fits4_run(tmp_path)
    raw_bytes = original.read_bytes()
    old_revision = read_metadata(image).artifact.created_at
    old_table = image.parent / 'fits_quantification.parquet'
    table_revision = read_metadata(old_table).artifact.created_at
    assert inspect_run_compatibility(tmp_path).outdated
    with pytest.raises(ValueError, match='read-only'):
        require_current_run(tmp_path)
    plan = api.plan_migration(tmp_path)
    assert plan is not None
    states = api.migrate(plan)
    assert len(states) == 1
    current = image.with_name(cst.ARRAY_RAW)
    assert current.exists() and not image.exists()
    assert original.read_bytes() == raw_bytes
    np.testing.assert_array_equal(ScopeIO.from_path(current).get_array().array, pixels)
    metadata = read_metadata(current)
    assert compatible(metadata)
    assert metadata.artifact.created_at == old_revision
    assert metadata.artifact.created_by == 'fits-io'
    assert metadata.custom_metadata['migration']['historical_lineage'] == 'preserved'
    assert metadata.custom_metadata['migration']['original_pipeline_meta']['version'] == '4.1.0'
    table = current.parent / cst.QUANTI_NAME
    measured = pd.read_parquet(table)
    assert measured['intensity_mean'].tolist() == [17.25]
    assert measured['experiment_id'].tolist() == ['saved-experiment']
    assert measured['cell_id'].tolist() == ['saved-cell']
    with tifffile.TiffFile(current) as tif:
        assert tif.imagej_metadata is not None
        assert '5.0.0' in tif.imagej_metadata['Info']
    rewritten = read_metadata(table)
    assert rewritten.artifact.created_at == table_revision
    refs = rewritten.artifact.derived_from
    assert isinstance(refs, list)
    assert refs[0]['artifact_path'] == current.name
    fields = pq.read_schema(table).metadata or {}
    assert naming.PARQUET_ARTIFACT in fields and naming.LEGACY_PARQUET_ARTIFACT not in fields
    assert (original.parent / '.acquisition').is_dir()
    assert not (original.parent / '.fits_experiment').exists()
    assert (tmp_path / '.pipeline/settings.toml').is_file()
    assert not (tmp_path / '.fits').exists()
    assert not inspect_run_compatibility(tmp_path).outdated
    assert api.plan_migration(tmp_path) is None
    assert list((tmp_path / '.pipeline/backup').glob('*/run/.fits/fits_settings.toml'))


def test_partial_manual_rename_remains_blocked_and_can_finish_migration(tmp_path: Path) -> None:
    """
    Recognize old state references after one file was already given its new name.
    """
    original, image, _ = _fits4_run(tmp_path)
    image.rename(image.with_name(cst.ARRAY_RAW))
    assert inspect_run_compatibility(tmp_path).outdated
    plan = api.plan_migration(tmp_path)
    assert plan is not None
    api.migrate(plan)
    assert not inspect_run_compatibility(tmp_path).outdated
    assert discover_saved_states(tmp_path)[0].original_image == original


def test_migration_collision_does_not_mutate_active_files(tmp_path: Path) -> None:
    """
    Never overwrite a competing target while planning migration.
    """
    _, image, _ = _fits4_run(tmp_path)
    target = image.with_name(cst.ARRAY_RAW)
    target.write_bytes(b'competing result')
    before = image.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        api.plan_migration(tmp_path)
    assert image.read_bytes() == before
    assert target.read_bytes() == b'competing result'


def test_compacted_legacy_migration_requires_rebuild_before_run(tmp_path: Path) -> None:
    """
    Naming adoption does not pretend that missing compacted intermediates exist.
    """
    _fits4_run(tmp_path, compacted=True)
    plan = api.plan_migration(tmp_path)
    assert plan is not None
    api.migrate(plan)
    assert (tmp_path / '.pipeline/upgrade_pending.json').is_file()
    with pytest.raises(ValueError, match='read-only'):
        require_current_run(tmp_path)
    assert api.plan_full_rebuild(tmp_path) is not None


def test_failed_header_update_rolls_back_names_and_preserves_original_snapshot(tmp_path: Path,
                                                                            monkeypatch: pytest.MonkeyPatch,
                                                                            ) -> None:
    """
    Restore old filenames, folders and bytes when metadata publication fails.
    """
    original, image, _ = _fits4_run(tmp_path)
    before = image.read_bytes()
    raw = original.read_bytes()
    plan = api.plan_migration(tmp_path)
    assert plan is not None

    def fail(*args: Any, **kwargs: Any) -> None:
        """
        Simulate an I/O failure after file moves have begun.
        """
        raise OSError('simulated header failure')

    monkeypatch.setattr('fisch.workflows.file_management.relocation.rewrite_metadata', fail)
    with pytest.raises(OSError, match='simulated'):
        api.migrate(plan)
    assert image.read_bytes() == before
    assert original.read_bytes() == raw
    assert (original.parent / '.fits_experiment').is_dir()
    assert not image.with_name(cst.ARRAY_RAW).exists()


def test_pre4_legacy_final_name_migrates_to_its_actual_stage(tmp_path: Path) -> None:
    """
    Recognize the historical FITS final filename when assigning a pre-4 checkpoint.
    """
    from test_file_management import legacy_run

    _, state, pixels = legacy_run(tmp_path)
    old = state.artifact(cst.ARTI_IMG)
    assert old is not None
    old.rename(old.with_name('fits_array.tif'))
    path = state.workdir / 'experiment_state.json'
    payload = json.loads(path.read_text())
    payload['artifacts'] = {kind: 'fits_array.tif' if value == cst.ARRAY_NAME else value
                             for kind, value in payload['artifacts'].items()}
    path.write_text(json.dumps(payload))
    plan = api.plan_migration(tmp_path)
    assert plan is not None
    migrated = api.migrate(plan)[0]
    assert migrated.migration_checkpoint == cst.StepName.BG_SUB
    current = migrated.artifact(cst.ARTI_IMG_BGSUB)
    assert current is not None and current.name == cst.ARRAY_BGSUB
    np.testing.assert_array_equal(ScopeIO.from_path(current).get_array().array, pixels)
    assert not inspect_run_compatibility(tmp_path).outdated
