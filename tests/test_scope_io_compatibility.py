"""Existing FIScH experiments remain usable after switching their I/O library."""

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

from scope_io import ScopeIO
from fisch.environment import constant as cst
from fisch.settings.models import ConvertSettings
from fisch.tasks.convert import convert
from fisch.workflows.artifacts.provenance import PARQUET_PROVENANCE_KEY, compatible, read_metadata
from fisch.workflows.definitions.registry import REGISTRY
from fisch.workflows.experiments import ExperimentState
from fisch.workflows.file_management.relocation import PortablePlan, _provenance
from fisch.workflows.metadata import PipelineMetadata


@pytest.mark.parametrize('historical', ['fits-io', 'fits_io'])
def test_recorded_io_producer_can_continue_with_scope_io(historical: str) -> None:
    """
    Append new channel parameters without rewriting historical producer identity.
    """
    metadata = PipelineMetadata.init().with_step(cst.StepName.CONVERT, historical, [0], {'channel': 'GFP'})
    recorded = metadata.steps[cst.StepName.CONVERT]
    updated = metadata.with_step(cst.StepName.CONVERT, cst.DIST_IO, [1], {'channel': 'RFP'})
    step = updated.steps[cst.StepName.CONVERT]
    assert step.created_by == historical
    assert step.version == recorded.version
    assert set(step.channels) == {'0', '1'}
    with pytest.raises(ValueError, match='previously created'):
        metadata.with_step(cst.StepName.CONVERT, 'unrelated-producer', [1], {})


def test_conversion_overwrites_historical_io_result_without_reprocessing_other_steps(tmp_path: Path) -> None:
    """
    Reconvert a real old-key TIFF while preserving the acquisition and saved lineage.
    """
    original = tmp_path / 'raw.tif'
    pixels = np.arange(64, dtype=np.uint16).reshape(8, 8)
    tifffile.imwrite(original, pixels, photometric='minisblack')
    raw_bytes = original.read_bytes()
    profile = REGISTRY[cst.StepName.CONVERT].profile
    old_profile = replace(profile, distribution='fits-io')
    first = convert(ConvertSettings(channel_labels=['GFP']),
                    ExperimentState.init(tmp_path, original, run_dir=tmp_path), old_profile)[0]
    output = first.artifact(cst.ARTI_IMG_RAW)
    assert output is not None
    payload = read_metadata(output).dump()
    payload['fits_io'] = payload.pop('artifact')
    with tifffile.TiffFile(output, mode='r+') as tif:
        tif.pages.first.tags[65000].overwrite(json.dumps(payload).encode())
    assert compatible(read_metadata(output))
    result = convert(ConvertSettings(channel_labels=['GFP'], overwrite=True), first, profile)[0]
    rewritten = result.artifact(cst.ARTI_IMG_RAW)
    assert rewritten is not None
    metadata = read_metadata(rewritten)
    np.testing.assert_array_equal(ScopeIO.from_path(rewritten).get_array().array, pixels)
    assert result.original_image.read_bytes() == raw_bytes
    assert metadata.artifact.created_by == 'scope-io'
    assert metadata.artifact.version == '3.0.0'
    assert metadata.custom_metadata['steps']['convert']['created_by'] == 'fits-io'
    with tifffile.TiffFile(rewritten) as tif:
        stored = json.loads(tif.pages.first.tags[65000].value)
    assert 'artifact' in stored and 'fits_io' not in stored


@pytest.mark.parametrize('key', ['fits_io', 'artifact'])
def test_parquet_and_location_updates_accept_both_metadata_keys(tmp_path: Path, key: str) -> None:
    """
    Read old tables and refresh path references using the same normalized model.
    """
    old = tmp_path / 'old'
    new = tmp_path / 'moved'
    payload: dict[str, Any] = {key: {'created_by': 'fits-io', 'version': '2.2.0',
                                    'created_at': '2026-11-01T09:00:00+00:00',
                                    'derived_from': [{'artifact_path': str(old / 'input.tif'),
                                                      'created_at': '2026-11-01T08:00:00+00:00'}]},
                               'custom_metadata': {'pipeline_meta': {'version': '5.0.0'}}}
    path = tmp_path / cst.QUANTI_NAME
    table = pa.Table.from_pandas(pd.DataFrame({'label': [1], 'intensity_mean': [42.5]}))
    table = table.replace_schema_metadata({PARQUET_PROVENANCE_KEY: json.dumps(payload).encode()})
    pq.write_table(table, path)
    before = path.read_bytes()
    metadata = read_metadata(path)
    assert compatible(metadata)
    assert metadata.artifact.created_by == 'fits-io'
    assert pd.read_parquet(path)['intensity_mean'].tolist() == [42.5]
    assert path.read_bytes() == before
    plan = PortablePlan(root=tmp_path, moves=((old, new),), states=(), fingerprints=())
    updated = _provenance(payload, old, new, plan)
    assert updated['artifact']['derived_from'][0]['artifact_path'] == 'input.tif'
    assert updated['artifact']['created_at'] == metadata.artifact.created_at
    assert updated['custom_metadata'] == payload['custom_metadata']
    assert 'fits_io' not in updated
