"""Workflow ordering is defined once and portable results are checked against it."""
from itertools import permutations
from pathlib import Path
from shutil import copytree

import numpy as np
import pytest
from scope_io import ScopeIO
from scope_io.metadata.models import ImageMetadata

from fisch.environment import constant as cst
from fisch.tasks.common.artifact_results import save_step_result
from fisch.workflows.artifacts.paths import image_for, image_input_for
from fisch.workflows.checks.artifacts import inspect_run, _workflow_order_problem
from fisch.workflows.checks.models import ArtifactRecord
from fisch.workflows.definitions.inputs import configured_profile
from fisch.workflows.definitions.registry import REGISTRY
from test_experiment_exclusion import _series


def _order(monkeypatch, preprocess):
    """Evaluate the constants as a fresh app launch with only WORKFLOW_ORDER edited."""
    order = (cst.StepName.CONVERT, *preprocess, cst.StepName.SEGMENT,
             cst.StepName.TRACK, cst.StepName.EDIT_TRACK,
             cst.StepName.DISTANCE_PROFILE, cst.StepName.EXTRACT)
    source = Path(cst.__file__).read_text(encoding='utf-8')
    start = source.index('WORKFLOW_ORDER:')
    end = source.index('\n\n\nDIST_PIPELINE', start)
    source = source[:start] + 'WORKFLOW_ORDER = ' + repr(tuple(map(str, order))) + source[end:]
    namespace = {'__name__': 'workflow_constants_test'}
    exec(compile(source, cst.__file__, 'exec'), namespace)
    for name in ('WORKFLOW_ORDER', 'IMAGE_STEPS', 'IMAGE_STAGE_ARTIFACTS', 'IMAGE_STAGE_NAMES', 'validate_workflow_order'):
        monkeypatch.setattr(cst, name, namespace[name])
    return order


@pytest.mark.parametrize('preprocess', list(permutations((cst.StepName.BG_SUB, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME))))
def test_one_order_drives_inputs_discovery_and_gui(tmp_path, monkeypatch, preprocess):
    order = _order(monkeypatch, preprocess)
    config = {step: {'enabled': True} for step in order}
    previous = cst.ARTI_IMG_RAW
    for step in preprocess:
        profile = configured_profile(REGISTRY[step].profile, config)
        assert profile.input_artifact == previous
        previous = cst.IMAGE_OUTPUTS[step]
    assert configured_profile(REGISTRY[cst.StepName.SEGMENT].profile, config).input_artifact == previous
    # Reload registry definitions in isolation to verify unconfigured defaults too.
    import fisch.workflows.definitions.registry as registry
    namespace = {'__name__': 'workflow_registry_test'}
    exec(compile(Path(registry.__file__).read_text(), registry.__file__, 'exec'), namespace)
    assert namespace['REGISTRY'][preprocess[0]].profile.input_artifact == cst.ARTI_IMG_RAW
    assert namespace['REGISTRY'][cst.StepName.SEGMENT].profile.input_artifact == previous
    for name in cst.IMAGE_STAGE_NAMES:
        (tmp_path / name).touch()
    assert image_for(tmp_path).name == cst.IMAGE_OUTPUT_NAMES[preprocess[-1]]
    import fisch.gui.file_preview.models as models
    namespace = {'__name__': models.__name__}
    exec(compile(Path(models.__file__).read_text(), models.__file__, 'exec'), namespace)
    assert {name: namespace['_FILE_STEPS'][name] for name in cst.IMAGE_STAGE_NAMES} == {
        name: step for step, name in cst.IMAGE_OUTPUT_NAMES.items()}
    config[preprocess[-1]]['enabled'] = False
    assert configured_profile(REGISTRY[cst.StepName.SEGMENT].profile, config).input_artifact == cst.IMAGE_OUTPUTS[preprocess[-2]]


def test_invalid_order_rejected(monkeypatch):
    order = list(cst.WORKFLOW_ORDER)
    first, second = order.index(cst.StepName.SEGMENT), order.index(cst.StepName.TRACK)
    order[first], order[second] = order[second], order[first]
    monkeypatch.setattr(cst, 'WORKFLOW_ORDER', tuple(order))
    with pytest.raises(ValueError, match='segment must precede track'):
        cst.validate_workflow_order()
    monkeypatch.setattr(cst, 'WORKFLOW_ORDER', tuple(order[:-1]))
    with pytest.raises(ValueError, match='every step exactly once'):
        cst.validate_workflow_order()


def test_portable_results_conflict_after_reorder(tmp_path, monkeypatch):
    root = tmp_path / 'original'
    root.mkdir()
    state = _series(root)[0]
    config = {str(step): {'enabled': step in (cst.StepName.CONVERT, cst.StepName.REGISTER_TIME, cst.StepName.BG_SUB), 'params': {}}
              for step in cst.WORKFLOW_ORDER}
    for step in (cst.StepName.REGISTER_TIME, cst.StepName.BG_SUB):
        profile = configured_profile(REGISTRY[step].profile, config)
        reader = ScopeIO.from_path(state.artifact(profile.input_artifact))
        state = save_step_result(reader, reader.get_array().array.astype(np.float32), reader.channel_labels, state, profile)
    assert not inspect_run(root, config, check_analysis=False).blocking_conflicts
    # Moving the complete acquisition does not change relative provenance.
    moved = tmp_path / 'moved'
    copytree(root, moved)
    assert not inspect_run(moved, config, check_analysis=False).blocking_conflicts
    from fisch.workflows.file_management.compaction import plan_compaction, apply_compaction
    compacted = tmp_path / 'compacted'
    copytree(root, compacted)
    apply_compaction(plan_compaction(compacted))
    assert not inspect_run(compacted, config, for_execution=False, check_analysis=False).blocking_conflicts
    _order(monkeypatch, (cst.StepName.BG_SUB, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME))
    report = inspect_run(moved, config, check_analysis=False)
    assert report.blocking_conflicts
    assert any('Workflow order changed' in record.problem for record in report.conflicts)
    assert {cst.StepName.BG_SUB, cst.StepName.REGISTER_TIME} <= {record.step for record in report.conflicts}
    compacted_report = inspect_run(compacted, config, for_execution=False, check_analysis=False)
    assert any('Workflow order changed' in record.problem for record in compacted_report.blocking_conflicts)


def test_order_history_survives_compacted_image_metadata(monkeypatch, tmp_path):
    metadata = ImageMetadata().with_custom_metadata({'workflow_order': ['register_time', 'bg_sub']})
    record = ArtifactRecord(tmp_path / cst.ARRAY_NAME, None, metadata)
    assert not _workflow_order_problem(record)
    _order(monkeypatch, (cst.StepName.BG_SUB, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME))
    assert 'Workflow order changed' in _workflow_order_problem(record)


def test_tuner_finds_metadata_beside_series(tmp_path, monkeypatch):
    monkeypatch.setattr("fisch.workflows.artifacts.paths.run_settings_path", lambda parent: tmp_path / "absent.toml")
    state = _series(tmp_path)[0]
    profile = configured_profile(REGISTRY[cst.StepName.BG_SUB].profile, {'convert': {'enabled': True}, 'bg_sub': {'enabled': True}})
    reader = ScopeIO.from_path(state.artifact(cst.ARTI_IMG_RAW))
    state = save_step_result(reader, reader.get_array().array.astype(np.float32), reader.channel_labels, state, profile)
    # No settings file: discovery must still find the acquisition's saved state.
    assert image_input_for(state.artifact(cst.ARTI_IMG_BGSUB), cst.StepName.BG_SUB) == state.artifact(cst.ARTI_IMG_RAW)
