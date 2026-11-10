"""One-time structure upgrades and explicit metadata/table refresh plans."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from dataclasses import dataclass, replace
import json
import os
import pandas as pd
import tomlkit
from pathlib import Path, PureWindowsPath
from fits.environment import constant as cst
from fits.environment.paths import EXPERIMENT_DIR_NAME, STATE_FILENAME, experiment_state_path, is_internal_path
from fits.channel_labels.lock import run_write_guard
from fits.channel_labels.persistence import atomic_table, atomic_bytes
from fits.workflows.experiments import ExperimentState, discover_saved_states, save_experiment_state
from fits.workflows.experiments.serialization import deserialize_experiment_state
from fits.workflows.file_management.transactions import FileUpdate
from fits.workflows.file_management.run_history import require_run_backup_space, stage_run_snapshot, publish_run_snapshot
from fits.workflows.definitions.inputs import IMAGE_OUTPUTS
from fits.workflows.checks.compatibility import inspect_run_compatibility
from fits.workflows.checks.locations import LocationReport, inspect_locations
from fits.tasks.analysis.aggregate import save_master_analysis_table
from fits.tasks.analysis.identity import add_quantification_ids
from fits.workflows.artifacts.provenance import compatible, read_metadata
from scope_io.writers.metadata_update import rewrite_metadata
from fits.workflows.file_management.migration import prepare_state, migrate_payload, accepted_inputs
from scope_io.metadata.models import ImageMetadata


@dataclass(frozen=True)
class PortablePlan:
    root: Path
    moves: tuple[tuple[Path, Path], ...]
    states: tuple[ExperimentState, ...]
    fingerprints: tuple[tuple[Path, int, int], ...]
    rebuild: bool = False
    series_moves: tuple[tuple[Path, Path], ...] = ()
    rebuild_series: tuple[Path, ...] = ()
    migrate: bool = False
    locations: LocationReport | None = None

    def describe(self) -> str:
        """
        Describe the exact move, metadata and table operations for review.
        """
        if self.locations is not None:
            return (self.locations.describe() + '\n\nUpdate saved references and regenerate affected master tables. '
                    'Portable experiment tables, pixels and measurements are preserved. '
                    'A complete run backup is retained before applying changes.')
        lines = ['Update the selected experiments using the current run directory.',
                 'Image pixels and measurement values are preserved during relocation/table refresh.']
        lines += [f'MOVE {source}\n  -> {target}' for source, target in self.moves]
        for state in self.states:
            lines.append(f'STATE {experiment_state_path(state.workdir)}')
            for name in (cst.FITS_QUANTI_NAME, cst.FITS_DISTANCE_PROFILE_NAME):
                lines.append(f'REFRESH portable identifiers and relative paths if present: {state.workdir / name}')
        lines.append('REGENERATE run master tables from existing measurements.')
        lines.append('RETAIN a complete original run folder under .fits/backup before applying these changes. '
                     'This uses additional disk space and allows restoring the original layout, files and metadata.')
        if self.rebuild:
            lines.extend(f'REBUILD processing for {path}' for path in self.rebuild_series)
            lines.append('REBUILD incompatible processing results afterward. This may take substantial time and change numerical results. Old outputs are retained.')
        return '\n'.join(lines)


def all_states(root: Path) -> list[ExperimentState]:
    """
    Load current and earlier-layout states for an explicit relocation plan.
    """
    status = inspect_run_compatibility(root)
    result = list(status.states)
    for path in status.old_states:
        raw = json.loads(path.read_text(encoding='utf-8'))
        result.append(ExperimentState(workdir=path.parent, run_dir=root, **deserialize_experiment_state(raw)))
    return result


def scoped_states(states: Sequence[ExperimentState], selected: Path | None) -> list[ExperimentState]:
    """
    Select states under a series, acquisition or run folder.
    """
    if selected is None:
        return list(states)
    selected = Path(selected).resolve()
    if selected.is_file():
        selected = selected.parent
    return [state for state in states if state.workdir == selected or selected in state.workdir.parents]


def plan_portable_update(root: Path,
                         *,
                         selected: Path | None = None,
                         upgrade: bool = False,
                         migrate: bool = False,
                         ) -> PortablePlan:
    """
    Plan reviewed grouping, metadata relocation and known-path updates.
    """
    root = Path(root).expanduser().resolve()
    status = inspect_run_compatibility(root)
    if status.outdated and not upgrade:
        raise ValueError('This run contains outdated experiments. Upgrade the run before refreshing paths/tags.')
    states = all_states(root)
    unassociated = [path for path in status.files if path.parent not in {state.workdir for state in states}]
    if unassociated:
        raise ValueError('Cannot associate processed files with an experiment state; no files changed:\n' + '\n'.join(map(str,
                                                                                                                          unassociated,
                                                                                                                          )))
    if upgrade and status.outdated:
        selected = None  # A mixed run must be upgraded as one coherent run.
    states = scoped_states(states, selected)
    if not states and (selected is not None or upgrade or migrate or not inspect_locations(root, ()).needs_update):
        raise ValueError('No experiment states were found for this selection. Unknown/orphan outputs require their matching state and original acquisition.')
    moves: list[tuple[Path, Path]] = []
    new_states: list[ExperimentState] = []
    series_moves: list[tuple[Path, Path]] = []
    watched: set[Path] = set()
    raw_targets: dict[Path, Path] = {}
    settings = root / '.fits/fits_settings.toml'
    if settings.is_file():
        watched.add(settings)
    watched.update(root / name for _, name in cst.MASTER_TABLES if (root / name).is_file())
    rebuild = False
    rebuild_parents = set()
    for path in status.files:
        try:
            incompatible = not compatible(read_metadata(path))
        except (OSError, ValueError):
            incompatible = True
        if incompatible:
            rebuild = True
            rebuild_parents.add(path.parent)
    for state in states:
        if migrate and state.workdir in status.outdated_folders:
            state = prepare_state(state)
        source = _resolve_original(root, state)
        group, target_source = _plan_source_move(root, source, raw_targets, moves)
        new_workdir = group / state.workdir.name
        if state.workdir != new_workdir:
            if new_workdir.exists():
                raise ValueError(f'Series destination already exists: {new_workdir}')
            moves.append((state.workdir, new_workdir))
        series_moves.append((state.workdir, new_workdir))
        artifacts = _plan_artifact_paths(state, new_workdir, target_source, watched)
        if state.migration_checkpoint is not None and not state.compacted:
            artifacts = _plan_checkpoint_name(state, new_workdir, artifacts, moves)
        _plan_metadata_moves(state, new_workdir, group, source, moves, watched)
        new_states.append(replace(state, workdir=new_workdir, artifacts=artifacts, run_dir=root))
    fingerprints = tuple((path, path.stat().st_size, path.stat().st_mtime_ns) for path in sorted(watched))
    numerical = tuple(new for old, new in series_moves if old in rebuild_parents)
    plan = PortablePlan(root,
                        tuple(moves),
                        tuple(new_states),
                        fingerprints,
                        rebuild and not migrate,
                        tuple(series_moves),
                        numerical,
                        migrate,
                        inspect_locations(root) if not migrate and not moves and not rebuild else None,
                        )
    _check_update_space(plan)
    return plan


def _plan_checkpoint_name(state: ExperimentState,
                          workdir: Path,
                          artifacts: dict[cst.ArtifactType, Path],
                          moves: list[tuple[Path, Path]],
                          ) -> dict[cst.ArtifactType, Path]:
    """
    Give a migrated final array its real stage name without recomputing its pixels.
    """
    stage = cst.StepName(state.migration_checkpoint)
    names: dict[cst.ArtifactType, str] = dict(zip(cst.IMAGE_STAGE_ARTIFACTS, cst.IMAGE_STAGE_NAMES, strict=True))
    old = state.artifact(cst.ARTI_IMG)
    if old is None or old.name != cst.FITS_ARRAY_NAME:
        return artifacts
    target = workdir / names[IMAGE_OUTPUTS[stage]]
    if (state.workdir / target.name).exists():
        raise ValueError(f'Cannot rename the migrated final array: {target.name} already exists.')
    moves.append((workdir / old.name, target))
    return {kind: Path(target.name) if path == Path(old.name) else path for kind, path in artifacts.items()}


def _check_update_space(plan: PortablePlan) -> None:
    """
    Budget relocation or migration without treating acquisitions as rewrites.
    """
    originals = {state.original_image for state in plan.states}
    sources = {source for source, target in plan.moves if target in originals}
    sources.update(path for path in originals if path.is_file())
    rewritten = {path for path, _, _ in plan.fingerprints if path not in sources}
    rewritten.update(plan.root / name for _, name in cst.MASTER_TABLES)
    require_run_backup_space(plan.root, rewritten)


def _resolve_original(root: Path, state: ExperimentState) -> Path:
    """
    Resolve the current original acquisition, rejecting ambiguous associations.
    """
    source = state.original_image
    try:
        source.relative_to(root)
        in_run = True
    except ValueError:
        in_run = False
    if not in_run or not source.is_file():
        local = state.workdir.parent / source.name
        matches = [path for path in root.rglob(source.name) if path.is_file() and not is_internal_path(path, root)]
        if local.is_file():
            matches = [local]
        if len(matches) != 1:
            raise ValueError(f'Cannot uniquely locate original acquisition {source.name}. No files changed.')
        source = matches[0]
    return source

def _plan_source_move(root: Path,
                      source: Path,
                      raw_targets: dict[Path, Path],
                      moves: list[tuple[Path, Path]],
                      ) -> tuple[Path, Path]:
    """
    Plan acquisition grouping once for all series sharing an original file.
    """
    grouped = (source.parent / EXPERIMENT_DIR_NAME).is_dir()
    group = source.parent if grouped or source.parent.name == source.stem else source.parent / source.stem
    group.resolve().relative_to(root)
    target_source = group / source.name
    if not grouped and source != target_source and group.exists():
        raise ValueError(f'Acquisition destination already exists: {group}. Resolve the collision before upgrading.')
    if source not in raw_targets:
        raw_targets[source] = target_source
        if source != target_source:
            moves.append((source, target_source))
    return group, target_source

def _plan_artifact_paths(state: ExperimentState,
                         new_workdir: Path,
                         target_source: Path,
                         watched: set[Path],
                         ) -> dict[cst.ArtifactType, Path]:
    """
    Rebind saved artifact paths and watch existing outputs for preview changes.
    """
    artifacts = {}
    for kind, path in state.artifacts.items():
        original = state.artifact(kind)
        if kind == cst.ARTI_RAW:
            target = target_source
        else:
            if original is None:
                continue
            try:
                relative = original.relative_to(state.workdir)
            except ValueError:
                relative = Path(original.name)
                if not (state.workdir / relative).is_file():
                    raise ValueError(f'Artifact cannot be safely rebound: {original}')
            if not (state.workdir / relative).is_file() and (state.workdir / original.name).is_file():
                relative = Path(original.name)
            target = new_workdir / relative
            actual = state.workdir / relative
            if actual.is_file():
                watched.add(actual)

        artifacts[kind] = Path(os.path.relpath(target, new_workdir))
    return artifacts

def _plan_metadata_moves(state: ExperimentState,
                         new_workdir: Path,
                         group: Path,
                         source: Path,
                         moves: list[tuple[Path, Path]],
                         watched: set[Path],
                         ) -> None:
    """
    Plan state, tuning, cache and retained-history relocation after the series move.
    """
    old_json = state.workdir / STATE_FILENAME
    state_json = experiment_state_path(state.workdir)
    actual_json = old_json if old_json.is_file() else state_json
    watched.add(actual_json)
    watched.add(source)
    watched.update(path for path in state.workdir.glob('fits_*') if path.is_file())
    # State and old metadata moves happen after the series directory move.
    metadata = group / EXPERIMENT_DIR_NAME
    new_json = experiment_state_path(new_workdir, acquisition=group)
    if old_json.is_file():
        moves.append((new_workdir / old_json.name, new_json))
    old_metadata = state.workdir / '.fits'
    if old_metadata.is_dir():
        for child in old_metadata.iterdir():
            category = {'viewer_cache': 'cache', 'legacy': 'backup', 'backup': 'backup'}.get(child.name, 'tuning')
            destination = metadata / category / new_workdir.name
            if category == 'tuning':
                destination /= child.name
            moves.append((new_workdir / '.fits' / child.name, destination))


def _relocated(value: Any, old_base: Path, new_base: Path, plan: PortablePlan) -> Any:
    """
    Rebind a known artifact path while retaining portable relative references.
    """
    if not isinstance(value, str) or not value:
        return value
    windows_absolute = PureWindowsPath(value).is_absolute()
    if '\\' in value:
        value = PureWindowsPath(value).as_posix()
    path = Path(value)
    old = path if path.is_absolute() else (old_base / path).resolve()
    mapped = old
    for source, target in plan.moves:
        try:
            mapped = target / mapped.relative_to(source)
        except ValueError:
            pass
    external_to_run = False
    try:
        old.relative_to(plan.root)
    except ValueError:
        external_to_run = True
    if mapped == old and (path.is_absolute() or windows_absolute) and (external_to_run or windows_absolute or not old.exists()):
        candidates = [new_base / old.name, new_base.parent / old.name]
        candidates += [folder for folder in (new_base, new_base.parent) if folder.name == old.name]
        for candidate in candidates:
            if candidate.exists():
                mapped = candidate
                break
    return Path(os.path.relpath(mapped, new_base)).as_posix()


def _provenance(payload: dict[str, Any], old_base: Path, new_base: Path, plan: PortablePlan) -> dict[str, Any]:
    """
    Return the current provenance.
    """
    metadata = ImageMetadata.from_dict(payload)
    refs = metadata.artifact.derived_from
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, dict) and 'artifact_path' in ref:
                ref['artifact_path'] = _relocated(ref['artifact_path'], old_base, new_base, plan)
    return metadata.dump()


def _refresh_table(path: Path, state: ExperimentState, old_base: Path, plan: PortablePlan) -> None:
    """
    Refresh table.
    """
    frame = pd.read_parquet(path)
    if path.name == cst.FITS_QUANTI_NAME:
        frame = add_quantification_ids(frame, state.portable_experiment_id)
    else:
        frame['experiment_id'] = state.portable_experiment_id
    frame = frame.drop(columns=[name for name in frame if name.startswith('condition_level_')])
    for column in ('image_path', 'mask_path', 'artifact_path', 'source_path', 'experiment_path'):
        if column in frame:
            frame[column] = frame[column].map(lambda value: _relocated(value, old_base, state.workdir, plan))
    atomic_table(frame,
                 path,
                 metadata_transform=lambda data: _updated_payload(data, path, state, old_base, plan),
                 )


def _updated_payload(data: dict[str, Any],
                     path: Path,
                     state: ExperimentState,
                     old_base: Path,
                     plan: PortablePlan,
                     ) -> dict[str, Any]:
    """
    Apply the same path rebinding and optional adoption to TIFF and Parquet metadata.
    """
    data = _provenance(data, old_base, state.workdir, plan)
    if plan.migrate:
        data = migrate_payload(ImageMetadata.from_dict(data), inputs=accepted_inputs(path, state)).dump()
    return data


def apply_portable_update(plan: PortablePlan) -> tuple[ExperimentState, ...]:
    """
    Apply reviewed moves and metadata/table updates in a rollback transaction.
    """
    with run_write_guard(plan.root):
        for path, size, modified in plan.fingerprints:
            if not path.is_file() or (path.stat().st_size, path.stat().st_mtime_ns) != (size, modified):
                raise ValueError(f'{path} changed after preview. Review the update again.')
        _check_update_space(plan)
        with FileUpdate(plan.root) as transaction:
            retained = stage_run_snapshot(plan.root, transaction, reason='migration' if plan.migrate else 'update')
            for source, target in plan.moves:
                transaction.move(source, target)
            _refresh_settings(plan, transaction)
            for state, (old_base, _) in zip(plan.states, plan.series_moves, strict=True):
                _apply_state_update(state, old_base, plan, transaction)
            for index, (_, workdir) in enumerate(plan.series_moves):
                obsolete = workdir / '.fits'
                if obsolete.is_dir() and not any(obsolete.iterdir()):
                    transaction.move(obsolete, transaction.backup / f'empty_metadata_{index}')
            # Masters include every current experiment, not only the selection.
            states = discover_saved_states(plan.root)
            for kind, name in cst.MASTER_TABLES:
                if plan.rebuild:
                    continue
                if plan.locations is not None and not any(issue.path == plan.root / name for issue in plan.locations.issues):
                    continue
                transaction.protect(plan.root / name)
                master = save_master_analysis_table(states, plan.root, artifact_kind=kind, output_name=name)
                if master is None:
                    (plan.root / name).unlink(missing_ok=True)
            if len([state for state in states if state.workdir in {item.workdir for item in plan.states}]) != len(plan.states):
                raise ValueError('State verification failed after relocation.')
            if plan.migrate:
                pending = plan.root / '.fits/upgrade_pending.json'
                if pending.is_file():
                    transaction.protect(pending)
                    pending.unlink()
            if retained is not None:
                publish_run_snapshot(plan.root, retained, transaction)
    return plan.states


def _apply_state_update(state: ExperimentState, old_base: Path, plan: PortablePlan, transaction: FileUpdate) -> None:
    """
    Publish one series state and refresh its image and measurement metadata.
    """
    needs_rebuild = plan.rebuild and state.workdir in plan.rebuild_series
    target = experiment_state_path(state.workdir, acquisition=state.original_image.parent)
    if plan.locations is not None and not any(issue.path == target for issue in plan.locations.issues):
        return
    transaction.parents(target.parent)
    transaction.protect(target)
    save_experiment_state(state)
    if plan.locations is not None:
        return
    # TIFF pixels/revision times stay unchanged. Rewrite private
    # provenance only when actual path references need rebinding.
    paths = [state.workdir / name for name in (*cst.IMAGE_STAGE_NAMES, cst.FITS_ARRAY_NAME, *cst.MASK_NAMES)]
    for template in (cst.FITS_REFERENCE_TEMPLATE, cst.FITS_ROI_TEMPLATE):
        paths.extend(sorted(state.workdir.glob(template.format(label='*'))))
    for path in paths:
        if not path.is_file() or needs_rebuild:
            continue
        try:
            payload = read_metadata(path)
        except (OSError, ValueError):
            if plan.rebuild:
                continue
            raise
        before = payload.dump()
        after = _updated_payload(json.loads(json.dumps(before)), path, state, old_base, plan)
        if before != after:
            transaction.protect(path)
            rewrite_metadata(path, ImageMetadata.from_dict(after))
    for name in (cst.FITS_QUANTI_NAME, cst.FITS_DISTANCE_PROFILE_NAME):
        path = state.workdir / name
        if path.is_file() and not needs_rebuild and (plan.migrate or old_base != state.workdir):
            transaction.protect(path)
            _refresh_table(path, state, old_base, plan)


def _refresh_settings(plan: PortablePlan, transaction: FileUpdate) -> None:
    """
    Rebind known run-owned settings paths; preserve comments/external paths.
    """
    path = plan.root / '.fits/fits_settings.toml'
    if not path.is_file():
        return
    before = path.read_text(encoding='utf-8')
    document = tomlkit.parse(before)
    previous = Path(str(document.get('run_dir', plan.root))).expanduser()
    document['run_dir'] = str(plan.root)
    locations = [(document, 'optimize')]
    runtime = document.get('runtime', {})
    locations.append((runtime, 'log_dir'))
    for section, field in locations:
        value = section.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            try:
                candidate = plan.root / candidate.relative_to(previous)
            except ValueError:
                continue
        else:
            candidate = plan.root / candidate
        rebound = (plan.root / _relocated(str(candidate), plan.root, plan.root, plan)).resolve()
        if (rebound == plan.root or plan.root in rebound.parents) and rebound.exists():
            section[field] = str(rebound)
    after = tomlkit.dumps(document)
    if after != before:
        transaction.protect(path)
        atomic_bytes(path, after.encode('utf-8'))


