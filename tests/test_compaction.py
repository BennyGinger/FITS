import hashlib
from pathlib import Path

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO

from fits.workflows.file_management.compaction import compact_run, plan_compaction, apply_compaction
from fits.environment.paths import experiment_state_path, experiment_backup
from fits.environment import constant as cst
from fits.gui.settings import SettingsAdapter
from fits.pipeline import start_pipeline
from fits.workflows.experiments import discover_saved_states, save_experiment_state


def prepared(tmp_path):
    source = tmp_path / "source.tif"
    pixels = np.arange(64, dtype=np.uint16).reshape(8, 8)
    tifffile.imwrite(source, pixels, photometric="minisblack", metadata={"axes": "YX"})
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "Test"
    adapter.set_runtime_value("execution", "batch")
    adapter.set_field_value(cst.StepName.CONVERT, "channel_labels", ["Red"])
    start_pipeline(adapter.save_to_run_dir(), terminal_progress=False)
    state = discover_saved_states(tmp_path)[0]
    image = state.artifact(cst.ARTI_IMG_RAW)
    reader = FitsIO.from_path(image)
    ref = reader.save_array((pixels > 20).astype(np.uint16), output_path=state.workdir / cst.FITS_REFERENCE_TEMPLATE.format(label="edge"),
                            export_channels="all", artifact_kind=cst.ARTI_REF)
    return state, state.original_image, ref


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_compact_retains_pixels_revisions_and_ref_bytes(tmp_path):
    state, source, ref = prepared(tmp_path)
    source_hash, ref_hash = digest(source), digest(ref)
    image = state.artifact(cst.ARTI_IMG_RAW)
    stamp = FitsIO.from_path(image).reader.metadata.fits_io.created_at
    previewed = []
    published = compact_run(tmp_path, choose=lambda report: "continue",
                            confirm=lambda plan: previewed.append(plan) or True)
    assert len(published) == 1
    assert image in previewed[0].remove
    assert not image.exists()
    compacted = FitsIO.from_path(published[0])
    assert compacted.reader.metadata.fits_io.created_at == stamp
    np.testing.assert_array_equal(compacted.get_array().array, np.arange(64).reshape(8, 8))
    assert digest(source) == source_hash
    assert digest(ref) == ref_hash
    state = discover_saved_states(tmp_path)[0]
    assert state.compacted
    assert state.artifact(cst.ARTI_IMG).name == cst.FITS_ARRAY_NAME


def test_compact_cancel_and_stale_preview_do_not_remove_inputs(tmp_path):
    from fits.workflows.runtime.errors import PipelineCancelled
    state, source, ref = prepared(tmp_path)
    image = state.artifact(cst.ARTI_IMG_RAW)
    with pytest.raises(PipelineCancelled):
        compact_run(tmp_path, choose=lambda report: "cancel", confirm=lambda plan: False)
    assert image.is_file()
    plan = plan_compaction(tmp_path)
    ref.touch()
    with pytest.raises(ValueError, match="changed after"):
        apply_compaction(plan)
    assert image.is_file()
    assert not (state.workdir / cst.FITS_ARRAY_NAME).exists()


def test_compact_failure_restores_previous_outputs(tmp_path, monkeypatch):
    import fits.workflows.file_management.compaction as compact
    state, source, ref = prepared(tmp_path)
    image = state.artifact(cst.ARTI_IMG_RAW)
    before = digest(image)
    def fail(*args, **kwargs):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(compact, "rewrite_metadata", fail)
    with pytest.raises(OSError, match="simulated"):
        apply_compaction(plan_compaction(tmp_path))
    assert digest(image) == before
    assert not discover_saved_states(tmp_path)[0].compacted


def test_compacted_run_requires_rebuild_and_keeps_original(tmp_path):
    from fits.workflows.checks.artifacts import inspect_run
    from fits.workflows.checks.decisions import apply_decision
    from fits.workflows.file_management.compaction import run_config
    state, source, ref = prepared(tmp_path)
    compact_run(tmp_path, choose=lambda report: "continue", confirm=lambda plan: True)
    report = inspect_run(tmp_path, run_config(tmp_path))
    assert report.conflicts
    config = apply_decision(run_config(tmp_path), report, "rebuild")
    assert config[cst.StepName.CONVERT]["params"]["overwrite"]
    from fits.settings.loader import run_settings_path
    start_pipeline(run_settings_path(tmp_path), terminal_progress=False, artifact_decision=lambda report: "rebuild")
    restored = discover_saved_states(tmp_path)[0]
    assert not restored.compacted
    assert restored.artifact(cst.ARTI_IMG_RAW).is_file()
    assert source.is_file() and ref.is_file()


def test_compact_rolls_back_after_canonical_was_published(tmp_path, monkeypatch):
    import fits.workflows.file_management.compaction as compact
    state, source, ref = prepared(tmp_path)
    before = experiment_state_path(state.workdir).read_bytes()
    monkeypatch.setattr(compact, "save_experiment_state", lambda state: (_ for _ in ()).throw(OSError("state save failed")))
    with pytest.raises(OSError, match="state save"):
        apply_compaction(plan_compaction(tmp_path))
    assert not (state.workdir / cst.FITS_ARRAY_NAME).exists()
    assert state.artifact(cst.ARTI_IMG_RAW).is_file()
    assert experiment_state_path(state.workdir).read_bytes() == before


def test_legacy_rebuild_preserves_original_results_and_ref_pixels(tmp_path):
    from dataclasses import replace
    from fits.workflows.artifacts.provenance import read_metadata
    from fits.settings.loader import run_settings_path
    from fits.workflows.checks.models import PreflightRequired
    from fits_io.writers.metadata_update import rewrite_metadata
    state, source, ref = prepared(tmp_path)
    image = state.artifact(cst.ARTI_IMG_RAW)
    old = read_metadata(image).with_custom_metadata({'pipeline_meta': {'version': '3.3.0'}})
    rewrite_metadata(image, old)
    old_hash = digest(image)
    before_ref = FitsIO.from_path(ref).get_array().array.copy()
    with pytest.raises(ValueError, match="outdated/read-only"):
        start_pipeline(run_settings_path(tmp_path), terminal_progress=False)
    assert digest(image) == old_hash
    start_pipeline(run_settings_path(tmp_path), terminal_progress=False,
                   artifact_decision=lambda report: 'rebuild', upgrading=True)
    preserved = list((experiment_backup(state.workdir)).rglob(image.name))
    assert len(preserved) == 1 and digest(preserved[0]) == old_hash
    assert read_metadata(image).custom_metadata['pipeline_meta']['version'].startswith('4.')
    np.testing.assert_array_equal(FitsIO.from_path(ref).get_array().array, before_ref)


def test_rebuild_restores_missing_raw_before_downstream(tmp_path, monkeypatch):
    import importlib
    from fits.workflows.artifacts.provenance import read_metadata
    from fits.workflows.checks.artifacts import inspect_run
    state, source, ref = prepared(tmp_path)
    raw = state.artifact(cst.ARTI_IMG_RAW)
    reader = FitsIO.from_path(raw)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_BGSUB).new_revision([
        {'artifact_path': raw.name, 'created_at': read_metadata(raw).fits_io.created_at}])
    bg = reader.save_array(reader.get_array().array, metadata=payload,
                           output_path=state.workdir / cst.FITS_ARRAY_BGSUB)
    state = state.with_complete_step(step_name=cst.StepName.BG_SUB,
        artifact_kind=cst.ARTI_IMG_BGSUB, artifact_path=bg)
    save_experiment_state(state)
    raw.unlink()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_runtime_value('execution', 'batch')
    adapter.set_step_enabled(cst.StepName.CONVERT, False)
    adapter.set_step_enabled(cst.StepName.BG_SUB, True)
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', ['Red'])
    report = inspect_run(tmp_path, adapter.as_mapping())
    assert report.conflicts
    assert (str(cst.StepName.CONVERT), raw) in report.rebuild_outputs
    monkeypatch.setattr(importlib.import_module('fits.tasks.bg_sub'), 'bg_sub',
                        lambda array, **kwargs: array.astype(np.float32) + .5)
    start_pipeline(adapter.save_to_run_dir(), terminal_progress=False,
                   artifact_decision=lambda report: 'rebuild')
    assert raw.is_file()
    assert read_metadata(bg).fits_io.derived_from[0]['created_at'] == read_metadata(raw).fits_io.created_at
    assert not inspect_run(tmp_path, adapter.as_mapping()).conflicts


@pytest.mark.parametrize("accept_preview", [True, False])
def test_legacy_rebuild_continues_to_compact_in_one_flow(tmp_path, accept_preview):
    from fits.workflows.artifacts.provenance import read_metadata
    from fits.settings.loader import run_settings_path
    from fits_io.writers.metadata_update import rewrite_metadata
    state, source, ref = prepared(tmp_path)
    image = state.artifact(cst.ARTI_IMG_RAW)
    old = read_metadata(image).with_custom_metadata({'pipeline_meta': {'version': '3.3.0'}})
    rewrite_metadata(image, old)
    decisions = []
    def choose(report):
        decisions.append(report)
        return 'rebuild'
    def rebuild(report):
        start_pipeline(run_settings_path(tmp_path), terminal_progress=False,
                       artifact_decision=lambda report: 'rebuild', upgrading=True)
    from fits.workflows.file_management.relocation import plan_portable_update, apply_portable_update
    from fits.workflows.file_management.rebuild import finish_upgrade
    update = plan_portable_update(tmp_path, upgrade=True)
    apply_portable_update(update)
    finish_upgrade(update, lambda: rebuild(None))
    if accept_preview:
        published = compact_run(tmp_path, choose=choose, confirm=lambda plan: True, rebuild=rebuild)
    else:
        from fits.workflows.runtime.errors import PipelineCancelled
        with pytest.raises(PipelineCancelled, match="cancelled at file preview"):
            compact_run(tmp_path, choose=choose, confirm=lambda plan: False, rebuild=rebuild)
        assert image.is_file()
        assert not discover_saved_states(tmp_path)[0].compacted
        # Closing the compact preview keeps a successful rebuild usable. The
        # next click must go straight to compact preview, without another rebuild.
        published = compact_run(tmp_path, choose=lambda report: pytest.fail('Unexpected rebuild'),
                                confirm=lambda plan: True)
    assert len(decisions) == 0
    assert published == (state.workdir / cst.FITS_ARRAY_NAME,)
    states = discover_saved_states(tmp_path)
    assert len(states) == 1 and states[0].compacted
    assert list((experiment_backup(state.workdir)).rglob(image.name))
    assert not image.exists()
    # A second click sees an already compacted run, not the retained old snapshots.
    assert compact_run(tmp_path, choose=lambda report: pytest.fail('Unexpected rebuild'),
                       confirm=lambda plan: pytest.fail('Already compacted')) == ()


def test_fully_rebuilt_final_is_compacted_without_an_extra_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Rebuild the final image, then compact its new outputs without an extra retained copy.
    """
    from test_file_management import legacy_run, mock_rebuild_processing
    from fits.workflows.file_management import api
    from fits.workflows.file_management.history import snapshots
    adapter, old, pixels = legacy_run(tmp_path, masks=True)
    mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    state = api.migrate(api.plan_migration(tmp_path))[0]
    final = state.artifact(cst.ARTI_IMG)
    assert final.name == cst.FITS_ARRAY_BGSUB
    before = final.read_bytes()
    assert not (state.workdir / cst.FITS_ARRAY_NAME).exists()
    plan = api.plan_full_rebuild(tmp_path)
    api.update_downstream(plan, lambda plan: start_pipeline(adapter.save_to_run_dir(), maintenance=plan,
                                                          terminal_progress=False))
    assert final.read_bytes() != before
    backups = snapshots(tmp_path)
    compact_run(tmp_path, choose=lambda report: 'continue', confirm=lambda plan: True)
    current = discover_saved_states(tmp_path)[0]
    assert current.compacted and current.artifact(cst.ARTI_IMG).name == cst.FITS_ARRAY_NAME
    np.testing.assert_array_equal(FitsIO.from_path(current.artifact(cst.ARTI_IMG)).get_array().array, pixels + 1)
    assert {entry.directory for entry in snapshots(tmp_path)} == {entry.directory for entry in backups}


def test_compacted_run_loads_without_missing_intermediate_or_drawing_warning(tmp_path: Path) -> None:
    """
    Intentional intermediate removal must not make retained arrays or drawings stale.
    """
    from fits.workflows.checks.artifacts import inspect_run
    from fits.workflows.file_management.compaction import run_config
    prepared(tmp_path)
    compact_run(tmp_path, choose=lambda report: 'continue', confirm=lambda plan: True)
    assert not inspect_run(tmp_path, run_config(tmp_path), for_execution=False).conflicts


def test_previously_saved_compacted_state_remains_readable(tmp_path: Path) -> None:
    """
    Read earlier persisted field names at the storage boundary without API aliases.
    """
    import json
    from fits.workflows.checks.artifacts import inspect_run
    from fits.workflows.file_management.compaction import can_compact, run_config
    prepared(tmp_path)
    compact_run(tmp_path, choose=lambda report: 'continue', confirm=lambda plan: True)
    state = discover_saved_states(tmp_path)[0]
    path = experiment_state_path(state.workdir)
    payload = json.loads(path.read_text())
    payload['archived'] = payload.pop('compacted')
    payload['archive_conflicts_accepted'] = payload.pop('compaction_conflicts_accepted')
    for current, previous in ((cst.ARTI_IMG_COMPACTED, 'image_archived'), (cst.ARTI_MASK_COMPACTED, 'mask_archived')):
        if current in payload['artifacts']:
            payload['artifacts'][previous] = payload['artifacts'].pop(current)
    path.write_text(json.dumps(payload))
    restored = discover_saved_states(tmp_path)[0]
    assert restored.compacted
    assert restored.artifact(cst.ARTI_IMG_COMPACTED).is_file()
    assert not can_compact(tmp_path)
    assert not inspect_run(tmp_path, run_config(tmp_path), for_execution=False).conflicts
