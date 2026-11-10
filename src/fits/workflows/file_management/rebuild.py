"""Explicit numerical rebuilding, separate from migration and relocation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any
from fits.workflows.experiments import ExperimentState, active_states, discover_saved_states, save_experiment_state
from fits.workflows.file_management.relocation import PortablePlan, scoped_states
from dataclasses import dataclass, replace
import json
import tomlkit
from pathlib import Path
from fits.environment import constant as cst
from fits.channel_labels.lock import run_write_guard
from fits.workflows.file_management.transactions import FileUpdate
from fits.workflows.checks.space import file_bytes, require_free_space, require_processing_space
from fits.workflows.file_management.snapshots import rebuild_backup_size, replacement_states, retain_rebuild_backups
from fits.workflows.checks.compatibility import inspect_run_compatibility
from fits.tasks.analysis.aggregate import save_master_analysis_table
from fits.environment.paths import experiment_state_path
from fits.workflows.file_management.compaction import run_config
from fits.workflows.definitions.inputs import configured_profile
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.analysis import include_master_analysis, outdated_master_tables
from fits.workflows.checks.decisions import apply_decision
from fits.workflows.checks.models import PreflightReport
from copy import deepcopy
from fits.workflows.artifacts.provenance import compatible, read_metadata
from fits.workflows.definitions.registry import REGISTRY
from fits.channel_labels.persistence import atomic_bytes
from fits.settings.loader import run_settings_path
from fits.workflows.artifacts.branch_masks import geometry, refresh_branch
from fits.tasks.reference_mask.artifact import load_reference_artifact
from fits.tasks.roi_mask.artifact import load_roi_artifact
from scope_io import ScopeIO
from fits.tasks.analysis.extraction.compartment_export import compartment_export_paths
from fits.tasks.analysis.extraction.manager import resolve_extraction_labels


@dataclass(frozen=True)
class ProcessingPlan:
    root: Path
    action: str
    scope: dict[Path, tuple[str, ...]]
    fingerprints: tuple[tuple[Path, int, int], ...]
    explanation: str = ''
    full_rebuild_series: tuple[Path, ...] = ()

    def fully_rebuilds(self, folder: Path) -> bool:
        """
        Identify series whose complete chain and superseded outputs are replaced.
        """
        return self.action == 'rebuild' or folder in self.full_rebuild_series

    def describe(self) -> str:
        """
        Describe the reviewed processing scope and preservation guarantees.
        """
        lines = [self.explanation, 'Rebuilding can take a long time. Final images, masks and measurements may change; '
                 'small numerical differences are possible even with the same settings. '
                 'Different settings or processing versions can also change results.']
        for series, steps in self.scope.items():
            lines.append(f'{series}\n  ' + ', '.join(steps))
        if self.action == 'rebuild' or self.full_rebuild_series:
            lines.append('The complete processing chain is rebuilt from the original acquisition, including final results. '
                         'Existing results and experiment state are backed up before processing starts. '
                         'REF/ROI drawings are kept; review their alignment if registration changes.')
        else:
            lines.append('The listed stale results will be replaced. Earlier-stage and unrelated results are preserved.')
        return '\n\n'.join(lines)


def _processing_plan(root: Path,
                      action: str,
                      scope: dict[Path, tuple[str, ...]],
                      explanation: str,
                      full_rebuild_series: tuple[Path, ...] = (),
                      ) -> ProcessingPlan:
    """
    Capture the exact files and series/steps needed for a processing preview.
    """
    files = set()
    settings = run_settings_path(root)
    if settings.is_file():
        files.add(settings)
    for state in discover_saved_states(root):
        if state.workdir not in scope:
            continue
        files.add(experiment_state_path(state.workdir))
        files.add(state.original_image)
        files.update(path for path in state.workdir.glob('fits_*') if path.is_file())
    fingerprints = tuple((path, path.stat().st_size, path.stat().st_mtime_ns) for path in sorted(files))
    plan = ProcessingPlan(Path(root), action, scope, fingerprints, explanation, full_rebuild_series)
    _check_processing_space(plan)
    return plan


def _check_processing_space(plan: ProcessingPlan) -> None:
    """
    Budget each scheduled output as one raw FITS array or preserved final array.
    """
    states = discover_saved_states(plan.root)
    replaced = replacement_states(states, plan.scope)
    backup_bytes = rebuild_backup_size(replaced)
    require_processing_space(plan.root, ((state, len(plan.scope.get(state.workdir, ()))) for state in states),
                             additional_bytes=backup_bytes)


def plan_full_rebuild(root: Path) -> ProcessingPlan | None:
    """
    Rebuild every existing or enabled workflow result from its original acquisition.
    """
    config = run_config(root)
    states = active_states(discover_saved_states(root))
    if not states:
        return None
    for state in states:
        if not state.original_image.is_file():
            raise ValueError(f'Full rebuilding requires the original acquisition: {state.original_image}. No results have been changed.')
    scope = full_rebuild_scope(states, config)
    return _processing_plan(root,
                            'rebuild',
                            scope,
                            'Rebuild all experiment results from the original acquisitions with current processing settings.',
                            )


def full_rebuild_scope(states: Sequence[ExperimentState],
                       config: Mapping[str, Any],
                       *,
                       available: set[Path] | None = None,
                       ) -> dict[Path, tuple[str, ...]]:
    """
    Share full-rebuild scope calculation with pre-migration reconstruction previews.
    """
    states = active_states(states)
    if not states:
        return {}
    selected = {step for state in states for step in _full_rebuild_steps(state, config, available)}
    enabled = {str(step): {'enabled': step in selected} for step in cst.WORKFLOW_ORDER}
    steps = _full_rebuild_steps(states[0], enabled, available)
    return {state.workdir: steps for state in states}


def _full_rebuild_steps(state: ExperimentState,
                        config: Mapping[str, Any],
                        available: set[Path] | None = None,
                        ) -> tuple[str, ...]:
    """
    Include previous results, enabled work and the producers needed to rebuild them.
    """
    steps: set[str] = {cst.StepName.CONVERT}
    for step in cst.WORKFLOW_ORDER:
        profile = REGISTRY[step].profile
        output = state.artifact(profile.output_artifact)
        existing = output is not None and (output in available if available is not None else output.is_file())
        if step == cst.StepName.EDIT_TRACK:
            existing = existing and output is not None and output.name in (cst.FITS_MASK_TRACK_EDITED, cst.FITS_MASK_TRACK_EDITED_FILTERED)
        if step in state.completed_steps or config.get(step, {}).get('enabled') or existing:
            steps.add(step)
    if cst.StepName.EXTRACT in steps and not steps.intersection({cst.StepName.SEGMENT, cst.StepName.TRACK}):
        steps.add(cst.StepName.SEGMENT)
    producers = {spec.profile.output_artifact: name for name, spec in REGISTRY.items()
                 if name != cst.StepName.EDIT_TRACK}
    while True:
        enabled = {str(step): {'enabled': step in steps} for step in cst.WORKFLOW_ORDER}
        required = set(steps)
        for step in steps:
            profile = configured_profile(REGISTRY[step].profile, enabled)
            required.update(producers[kind] for kind in (profile.input_artifact, *profile.additional_artifacts)
                            if kind in producers)
        if required == steps:
            return tuple(str(step) for step in cst.WORKFLOW_ORDER if step in steps)
        steps = required


def plan_downstream_update(root: Path) -> ProcessingPlan | None:
    """
    Plan only processing affected by missing inputs or changed revisions.
    """
    config = run_config(root)
    report = inspect_run(root, config, for_execution=False)
    scope = _downstream_scope(report, config)
    return _processing_plan(root, 'downstream', scope, report.describe()) if scope else None


def _downstream_scope(report: PreflightReport, config: Mapping[str, Any]) -> dict[Path, tuple[str, ...]]:
    """
    Resolve only stale outputs through the existing artifact-decision planner.
    """
    scope = {}
    for state in report.states:
        records = tuple(record for record in report.records if record.path.parent == state.workdir)
        if not any(record.problem and record.step is not None for record in records):
            continue
        local = PreflightReport(records, (), (), (state,))
        baseline = json.loads(json.dumps(config))
        for step in cst.WORKFLOW_ORDER:
            baseline.setdefault(step, {'enabled': False, 'params': {}}).setdefault('params', {})['overwrite'] = False
        resolved = apply_decision(baseline, local, 'rebuild')
        steps = tuple(str(step) for step in cst.WORKFLOW_ORDER
                      if resolved.get(step, {}).get('enabled') and resolved[step].get('params', {}).get('overwrite'))
        if steps:
            scope[state.workdir] = steps
    return scope


def full_rebuild_folders(states: Sequence[ExperimentState]) -> tuple[Path, ...]:
    """
    Find compacted or migrated checkpoints that require complete reconstruction.
    """
    return tuple(state.workdir for state in active_states(states) if state.compacted or state.migration_checkpoint is not None)


def plan_required_rebuild(root: Path) -> ProcessingPlan | None:
    """
    Combine complete checkpoint reconstruction with other experiments' stale outputs.
    """
    config = run_config(root)
    report = inspect_run(root, config, for_execution=False)
    if report.outdated_masters:
        config = include_master_analysis(config, report.outdated_masters, report.records)
        report = inspect_run(root, config, for_execution=False)
    full = full_rebuild_folders(report.states)
    scope = _downstream_scope(report, config)
    targets = [state for state in report.states if state.workdir in full]
    for state in targets:
        if not state.original_image.is_file():
            raise ValueError(f'Full rebuilding requires the original acquisition: {state.original_image}. No results have been changed.')
    scope.update(full_rebuild_scope(targets, config))
    if not scope:
        return None
    return _processing_plan(root, 'required', scope,
                            'Rebuild the reviewed results. Compacted and migrated experiments are fully reconstructed; '
                            'other experiments rebuild only outdated outputs.\n\n' + report.describe(), full)


def rebuild_analysis_tables(root: Path) -> None:
    """
    Regenerate outdated masters from verified active results under the writer lock.
    """
    with run_write_guard(root):
        states = discover_saved_states(root)
        paths = outdated_master_tables(root, states)
        config = run_config(root)
        report = inspect_run(root, config, for_execution=False)
        # This action explicitly requests combined analysis, including its prerequisites.
        config = include_master_analysis(config, report.outdated_masters, report.records)
        report = inspect_run(root, config, for_execution=False)
        if report.blocking_conflicts:
            raise ValueError('Rebuild the outdated experiment results before combined analysis.\n' + report.describe())
        for kind, name in cst.MASTER_TABLES:
            if root / name in paths:
                save_master_analysis_table(states, root, artifact_kind=kind, output_name=name)


def execution_config(config: Mapping[str, Any], plan: ProcessingPlan) -> dict[str, Any]:
    """
    Use existing settings; execution_scope narrows each series to reviewed work.
    """
    result = deepcopy(dict(config))
    steps = {step for values in plan.scope.values() for step in values}
    for step in cst.WORKFLOW_ORDER:
        entry = result.setdefault(step, {'enabled': False, 'params': {}})
        entry.setdefault('params', {})['overwrite'] = step in steps
        if step in steps:
            entry['enabled'] = True
        elif step not in (cst.StepName.CONVERT, cst.StepName.REGISTER_CHANNEL,
                          cst.StepName.REGISTER_TIME, cst.StepName.BG_SUB):
            entry['enabled'] = False
    if result.get(cst.StepName.EXTRACT, {}).get('enabled'):
        for producer in (cst.StepName.TRACK, cst.StepName.SEGMENT):
            if config.get(producer, {}).get('enabled'):
                result[producer]['enabled'] = True
                if producer == cst.StepName.TRACK and config.get(cst.StepName.EDIT_TRACK, {}).get('enabled'):
                    result[cst.StepName.EDIT_TRACK]['enabled'] = True
                break
    return result


def execute_plan(plan: ProcessingPlan, run: Callable[[ProcessingPlan], None]) -> None:
    """
    Call the normal GUI/CLI pipeline only after the processing preview is accepted.
    """
    with run_write_guard(plan.root):
        for path, size, modified in plan.fingerprints:
            if not path.is_file() or (path.stat().st_size, path.stat().st_mtime_ns) != (size, modified):
                raise ValueError(f'{path} changed after preview. Review the processing action again.')
        _check_processing_space(plan)
        replaced = replacement_states(discover_saved_states(plan.root), plan.scope)
        if replaced:
            retain_rebuild_backups(plan.root, replaced)
    run(plan)
    with run_write_guard(plan.root):
        states = {state.workdir: state for state in discover_saved_states(plan.root)}
        _verify_processing_outputs(plan, states)
        full_scope = {folder: steps for folder, steps in plan.scope.items() if plan.fully_rebuilds(folder)}
        if full_scope:
            _finish_full_rebuild(replace(plan, scope=full_scope), states)
        _verify_processing_dependencies(plan)


def _verify_processing_outputs(plan: ProcessingPlan, states: Mapping[Path, ExperimentState]) -> None:
    """
    Require every reviewed output to exist with current provenance after processing.
    """
    for folder, steps in plan.scope.items():
        state = states.get(folder)
        if state is not None and state.excluded:
            continue
        for step in steps:
            profile = REGISTRY[step].profile
            expected = folder / profile.output_name
            path = expected if expected.is_file() else state.artifact(profile.output_artifact) if state is not None else None
            if path is None or not path.is_file() or not compatible(read_metadata(path)):
                raise ValueError(f'Processing did not finish: {folder}, {step}. Completed files and backups are preserved; review Manage files to continue.')
            if plan.fully_rebuilds(folder) and read_metadata(path).custom_metadata.get('migration'):
                raise ValueError(f'Full rebuilding did not replace the migrated result: {path}. Your backup is preserved.')


def _verify_processing_dependencies(plan: ProcessingPlan) -> None:
    """
    Apply the ordinary artifact checker to outputs produced by the reviewed work.
    """
    config = execution_config(run_config(plan.root), plan)
    report = inspect_run(plan.root, config, for_execution=False)
    unresolved = [record for record in report.conflicts
                  if record.path.parent in plan.scope and record.step in plan.scope[record.path.parent]]
    if unresolved:
        raise ValueError('Some rebuilt inputs still need attention:\n' + '\n'.join(
            f'{record.path}: {record.problem}' for record in unresolved))


def _finish_full_rebuild(plan: ProcessingPlan, states: Mapping[Path, ExperimentState]) -> None:
    """
    Remove superseded active filenames only after all replacement outputs exist.
    """
    with FileUpdate(plan.root) as transaction:
        for index, folder in enumerate(plan.scope):
            state = states[folder]
            artifacts: dict[cst.ArtifactType, Path] = {kind: path for kind, path in state.artifacts.items()
                         if kind not in (cst.ARTI_IMG_COMPACTED, cst.ARTI_MASK_COMPACTED)}
            rebuilt = replace(state, artifacts=artifacts)
            transaction.protect(experiment_state_path(folder))
            save_experiment_state(rebuilt)
            kept = {rebuilt.artifact(kind) for kind in artifacts}
            params = run_config(plan.root).get(cst.StepName.EXTRACT, {}).get('params', {})
            if params.get('compartments') and params.get('save_compartment_masks'):
                config = execution_config(run_config(plan.root), plan)
                profile = configured_profile(REGISTRY[cst.StepName.EXTRACT].profile, config)
                _, source = resolve_extraction_labels(rebuilt, profile)
                kept.update(compartment_export_paths(source))
            kept.update(folder / REGISTRY[step].profile.output_name for step in plan.scope[folder])
            for name in cst.MANAGED_NAMES:
                path = folder / name
                if path.is_file() and path not in kept:
                    transaction.move(path, transaction.backup / 'superseded' / str(index) / name)
        _save_rebuilt_workflow(plan, transaction)
        _verify_processing_dependencies(plan)


def _save_rebuilt_workflow(plan: ProcessingPlan, transaction: FileUpdate) -> None:
    """
    Keep saved enabled steps consistent with the workflow that was fully rebuilt.
    """
    path = run_settings_path(plan.root)
    if not path.is_file():
        return
    document = tomlkit.parse(path.read_text(encoding='utf-8'))
    for step in {step for steps in plan.scope.values() for step in steps}:
        if step not in document:
            document[step] = tomlkit.table()
        document[step]['enabled'] = True
    transaction.protect(path)
    atomic_bytes(path, tomlkit.dumps(document).encode('utf-8'))


def mark_upgrade_pending(root: Path, pending: bool, states: Sequence[ExperimentState] = ()) -> None:
    """
    Record or clear the required steps for an interrupted explicit full rebuild.
    """
    marker = root / '.fits' / 'upgrade_pending.json'
    if pending:
        data = json.loads(marker.read_text()) if marker.is_file() else {'status': 'Rebuild required before processing', 'required_steps': {}}
        for state in states:
            key = state.workdir.relative_to(root).as_posix()
            previous = data['required_steps'].get(key, [])
            data['required_steps'][key] = list(dict.fromkeys([*previous, *state.completed_steps]))
        marker.parent.mkdir(parents=True, exist_ok=True)
        atomic_bytes(marker, json.dumps(data).encode())
    else:
        marker.unlink(missing_ok=True)


def finish_upgrade(plan: PortablePlan, rebuild: Callable[[], None]) -> None:
    """
    Keep a failed/cancelled numerical upgrade visibly read-only and resumable.
    """
    pending = plan.root / '.fits' / 'upgrade_pending.json'
    if not plan.rebuild and not pending.exists():
        return
    scope = {state.workdir: state.completed_steps for state in plan.states
             if state.workdir in plan.rebuild_series}
    _check_processing_space(ProcessingPlan(plan.root, 'rebuild', scope, ()))
    mark_upgrade_pending(plan.root,
                         True,
                         [state for state in plan.states if state.workdir in plan.rebuild_series],
                         )
    required = json.loads(pending.read_text()).get("required_steps", {})
    rebuild()
    current = {state.workdir: state for state in discover_saved_states(plan.root)}
    for expected in plan.states:
        if expected.workdir.relative_to(plan.root).as_posix() not in required:
            continue
        state = current.get(expected.workdir)
        if state is None:
            raise ValueError(f'Upgrade incomplete: {expected.workdir}')
        for step in required.get(expected.workdir.relative_to(plan.root).as_posix(), expected.completed_steps):
            if step not in REGISTRY:
                continue
            path = state.artifact(REGISTRY[step].profile.output_artifact)
            if path is None or not path.is_file() or not compatible(read_metadata(path)):
                raise ValueError(f'Upgrade incomplete: {expected.workdir.name}, {step}. Completed work/history are retained; resume through Manage files.')
    status = inspect_run_compatibility(plan.root)
    remaining = [problem for problem in status.problems if not problem.startswith('An experiment upgrade')]
    if remaining:
        raise ValueError('Upgrade incomplete:\n' + '\n'.join(remaining))
    with run_write_guard(plan.root):
        with FileUpdate(plan.root) as transaction:
            for kind, name in cst.MASTER_TABLES:
                transaction.protect(plan.root / name)
                save_master_analysis_table(list(current.values()),
                                           plan.root,
                                           artifact_kind=kind,
                                           output_name=name,
                                           )
    mark_upgrade_pending(plan.root, False)


def geometry_reviews(root: Path, selected: Path | None = None) -> tuple[tuple[Path, Path], ...]:
    """
    Find drawings whose registration geometry needs explicit review.
    """
    result = []
    for state in scoped_states(discover_saved_states(root), selected):
        image = state.artifact(cst.ARTI_IMG)
        if image is None or not image.is_file():
            continue
        for template in (cst.FITS_REFERENCE_TEMPLATE, cst.FITS_ROI_TEMPLATE):
            for path in state.workdir.glob(template.format(label='*')):
                if geometry(read_metadata(path)) != geometry(read_metadata(image)):
                    result.append((path, image))
    return tuple(result)


def accept_reviewed_geometry(root: Path, reviews: Sequence[tuple[Path, Path]]) -> None:
    """
    Apply only an explicit user's acceptance of existing drawing alignment.
    """
    with run_write_guard(root):
        require_free_space(root, 2 * file_bytes(path for path, _ in reviews), action='update REF/ROI alignment metadata')
        with FileUpdate(root) as transaction:
            for path, image in reviews:
                reader = ScopeIO.from_path(image)
                loader = load_roi_artifact if path.match(cst.FITS_ROI_TEMPLATE.format(label='*')) else load_reference_artifact
                loader(path,
                       source_path=image,
                       source_axes=reader.axes,
                       source_shape=reader.reader.shape,
                       source_channels=tuple(reader.channel_labels),
                       )
                transaction.protect(path)
                refresh_branch(path, image, accept_geometry=True)


def upgrade_execution_config(root: Path,
                             config: Mapping[str, Any],
                             settings_path: Path,
                             ) -> tuple[dict[str, Any], list[ExperimentState]]:
    """
    Select incompatible/pending series; a run-wide lock does not rebuild healthy data.
    """
    root = Path(root)
    marker = root / '.fits/upgrade_pending.json'
    required = json.loads(marker.read_text()).get('required_steps', {}) if marker.is_file() else {}
    target_paths = {root / path for path in required}
    force = False
    for path in inspect_run_compatibility(root).files:
        try:
            incompatible = not compatible(read_metadata(path))
        except (OSError, ValueError):
            incompatible = True
        if incompatible:
            target_paths.add(path.parent)
            force = True
    states = [state for state in discover_saved_states(root) if state.workdir in target_paths]
    if not states:
        raise ValueError('No matching experiments are available to resume this upgrade.')
    steps = {step for state in states for step in state.completed_steps}
    steps.update(step for values in required.values() for step in values)
    steps.add(cst.StepName.CONVERT)
    resolved = deepcopy(dict(config))
    document = tomlkit.parse(settings_path.read_text(encoding='utf-8'))
    for step in steps:
        if step not in cst.WORKFLOW_ORDER:
            continue
        resolved.setdefault(step, {})['enabled'] = True
        if force:
            resolved[step].setdefault('params', {})['overwrite'] = True
        if step not in document:
            document[step] = tomlkit.table()
        document[step]['enabled'] = True
    _check_processing_space(ProcessingPlan(root, 'rebuild',
                                          {state.workdir: tuple(steps) for state in states}, ()))
    atomic_bytes(settings_path, tomlkit.dumps(document).encode('utf-8'))
    return resolved, states
