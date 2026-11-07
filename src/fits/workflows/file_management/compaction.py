"""Explicit compact previews and rollback-protected canonical artifact publication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from dataclasses import dataclass, replace
import os
import shutil
import tempfile
from pathlib import Path
from fits.workflows.artifacts.provenance import compatible, read_metadata
from fits.channel_labels.lock import run_write_guard
from fits.environment import constant as cst
from fits.environment.paths import experiment_cache, experiment_state_path
from fits.settings.loader import load_settings, run_settings_path
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.models import PreflightReport, PreflightRequired
from fits.workflows.checks.planning import downstream_steps
from fits.workflows.experiments import active_states, discover_saved_states, save_experiment_state, ExperimentState
from fits_io.writers.metadata_update import rewrite_metadata
from fits.workflows.file_management.history import snapshots
from fits.workflows.checks.space import file_bytes, require_free_space
from fits.workflows.runtime.errors import PipelineCancelled
from fits.workflows.checks.compatibility import require_current_run


@dataclass(frozen=True)
class CompactionSelection:
    state: ExperimentState
    image: Path
    mask: Path | None


@dataclass(frozen=True)
class CompactionPlan:
    root: Path
    selections: tuple[CompactionSelection, ...]
    remove: tuple[Path, ...]
    fingerprints: tuple[tuple[Path, int, int], ...]
    conflicts_accepted: bool = False
    absent_targets: tuple[Path, ...] = ()
    backup_bytes: int = 0

    def describe(self) -> str:
        """
        Describe exactly which essential files are kept and intermediates removed.
        """
        lines = ["KEEP original acquisitions, REF/ROI masks, measurements, settings and reports."]
        for selection in self.selections:
            lines.append(f"IMAGE: {selection.image} -> {cst.FITS_ARRAY_NAME}")
            if selection.mask is not None:
                lines.append(f"MASK: {selection.mask} -> {cst.FITS_MASKS_COMPACTED}")
            for name in (cst.FITS_ARRAY_NAME, cst.FITS_MASKS_COMPACTED):
                target = selection.state.workdir / name
                if target.exists():
                    lines.append(f"REPLACE existing canonical output: {target}")
        lines.append("\nREMOVE these exact superseded artifacts/cache files:")
        lines.extend(str(path) for path in self.remove)
        if self.conflicts_accepted:
            lines.append("\nExisting downstream results will be retained despite provenance conflicts.")
        if self.backup_bytes:
            lines.append(f"\nRetained backups occupy approximately {self.backup_bytes / 1024**2:.1f} MiB. Compaction keeps them. Use Manage files to review/delete retained backups and recover more space.")
        return "\n".join(lines)


def run_config(root: Path) -> dict[str, Any]:
    """
    Compact config.
    """
    path = run_settings_path(root)
    if path.is_file():
        return load_settings(path)
    states = active_states(discover_saved_states(root))
    return {step: {"enabled": any(step in state.completed_steps for state in states), "params": {}}
            for step in cst.WORKFLOW_ORDER}


def can_compact(root: Path) -> bool:
    """
    Offer compaction only for compatible experiments with un-compacted saved images.
    """
    return any(not state.compacted and (image := state.artifact(cst.ARTI_IMG)) is not None
               and image.is_file() and compatible(read_metadata(image))
               for state in active_states(discover_saved_states(root)))


def plan_compaction(root: Path, *, conflicts_accepted: bool = False) -> CompactionPlan:
    """
    Plan canonical outputs and exact intermediate removal without creating a backup.
    """
    root = root.expanduser().resolve()
    selections = []
    remove = set()
    watched = set()
    states = active_states(discover_saved_states(root))
    if not states:
        raise ValueError("No saved experiments were found. Convert and process the run first.")
    for state in states:
        if state.compacted:
            continue
        images = [state.workdir / name for name in cst.IMAGE_STAGE_NAMES]
        image = next((path for path in reversed(images) if path.is_file()), None)
        if state.migration_checkpoint is not None:
            accepted = state.artifact(cst.ARTI_IMG)
            if accepted is not None and accepted.is_file():
                image = accepted
        if image is None:
            raise ValueError(f"{state.workdir}: earlier-version results are read-only; rebuild before compacting.")
        mask_names = dict.fromkeys((cst.FITS_MASK_TRACK_EDITED_FILTERED, cst.FITS_MASK_TRACK_EDITED,
                                   *cst.TRACKING_NAMES, *cst.SEGMENTATION_NAMES))
        masks = [state.workdir / name for name in mask_names]
        active = state.artifact(cst.ARTI_TRACK)
        mask = active if active is not None and active.is_file() else next((path for path in masks if path.is_file()),
                                                                           None,
                                                                           )
        for path in (image, mask):
            if path is not None and not compatible(read_metadata(path)):
                raise ValueError(f"{path}: earlier-version or incomplete provenance; rebuild before compacting.")
        selections.append(CompactionSelection(state, image, mask))
        remove.update(path for path in (*images, *masks) if path.is_file()
                      and path.name not in (cst.FITS_ARRAY_NAME, cst.FITS_MASKS_COMPACTED))
        cache = experiment_cache(state.workdir)
        remove.update(state.workdir / name for name in cst.COMPARTMENT_MASK_NAMES
                      if (state.workdir / name).is_file())
        if cache.is_dir():
            remove.update(path for path in cache.rglob("*") if path.is_file())
        watched.add(experiment_state_path(state.workdir))
        watched.update(path for path in state.workdir.glob("*.tif") if path.is_file())
        watched.update(path for path in state.workdir.glob("*.parquet") if path.is_file())
    watched.update(remove)
    fingerprints = tuple((path, path.stat().st_size, path.stat().st_mtime_ns) for path in sorted(watched))
    absent = tuple(state.workdir / name for state in (selection.state for selection in selections)
                   for name in (cst.FITS_ARRAY_NAME, cst.FITS_MASKS_COMPACTED)
                   if not (state.workdir / name).exists())
    backup_bytes = sum(entry.size for entry in snapshots(root))
    plan = CompactionPlan(root,
                       tuple(selections),
                       tuple(sorted(remove)),
                       fingerprints,
                       conflicts_accepted,
                       absent,
                       backup_bytes,
                       )
    _check_compaction_space(plan)
    return plan


def _check_compaction_space(plan: CompactionPlan) -> None:
    """
    Budget canonical outputs, publication scratch files and rollback copies.
    """
    sources = {path for selection in plan.selections for path in (selection.image, selection.mask)
               if path is not None}
    protected = set(plan.remove)
    for selection in plan.selections:
        protected.update(selection.state.workdir / name for name in (cst.FITS_ARRAY_NAME, cst.FITS_MASKS_COMPACTED))
        protected.add(experiment_state_path(selection.state.workdir))
    require_free_space(plan.root, file_bytes(protected) + 2 * file_bytes(sources), action='compact this run')


def apply_compaction(plan: CompactionPlan) -> tuple[Path, ...]:
    """
    Apply the exact preview under the same run lock used by pipeline writes.
    """
    with run_write_guard(plan.root):
        return _apply_compaction(plan)


def _apply_compaction(plan: CompactionPlan) -> tuple[Path, ...]:
    """
    Publish canonical results transactionally, then remove superseded intermediates.
    """
    for path in plan.absent_targets:
        if path.exists():
            raise ValueError(f"{path} changed after the compact preview; preview again.")
    for path, size, modified in plan.fingerprints:
        if not path.is_file() or (path.stat().st_size, path.stat().st_mtime_ns) != (size, modified):
            raise ValueError(f"{path} changed after the compact preview; preview again.")
    if not plan.selections:
        return ()
    _check_compaction_space(plan)
    backup_dir = Path(tempfile.mkdtemp(prefix=".fits_compact_", dir=plan.root))
    backups = {}
    created = []
    touched = []
    preserve_backups = False
    try:
        targets = set(plan.remove)
        for selected in plan.selections:
            targets.update(selected.state.workdir / name for name in
                           (cst.FITS_ARRAY_NAME, cst.FITS_MASKS_COMPACTED))
            targets.add(experiment_state_path(selected.state.workdir))
        for index, path in enumerate(sorted(targets)):
            if path.is_file():
                backup = backup_dir / str(index)
                try:
                    os.link(path, backup)
                except OSError:
                    shutil.copy2(path, backup)
                backups[path] = backup
        published = []
        for selected in plan.selections:
            state = selected.state
            artifacts = dict(state.artifacts)
            for source, target_name, role in (
                (selected.image, cst.FITS_ARRAY_NAME, cst.ARTI_IMG),
                (selected.mask, cst.FITS_MASKS_COMPACTED, None),
            ):
                if source is None:
                    continue
                metadata = read_metadata(source)
                payload = metadata.with_custom_metadata({"compaction": {
                    "source_artifact": source.name,
                    "conflicts_accepted": plan.conflicts_accepted,
                }})
                target = state.workdir / target_name
                touched.append(target)
                if target not in backups:
                    created.append(target)
                rewrite_metadata(source, payload, output_path=target)
                verified = read_metadata(target)
                if verified.fits_io.created_at != metadata.fits_io.created_at:
                    raise ValueError(f"Compact verification failed: {target}")
                published.append(target)
                if role == cst.ARTI_IMG:
                    artifacts[cst.ARTI_IMG] = Path(target.name)
                    artifacts[cst.ARTI_IMG_COMPACTED] = Path(target.name)
                else:
                    kind = cst.ARTI_TRACK if metadata.fits_io.artifact_type == cst.ARTI_TRACK else cst.ARTI_SEG
                    artifacts[kind] = Path(target.name)
                    artifacts[cst.ARTI_MASK_COMPACTED] = Path(target.name)
            compacted = replace(state,
                               artifacts=artifacts,
                               compacted=True,
                               compaction_conflicts_accepted=plan.conflicts_accepted,
                               )
            state_path = experiment_state_path(state.workdir)
            touched.append(state_path)
            save_experiment_state(compacted)
        # Originals stay in place until every retained artifact and state is verified.
        for path in plan.remove:
            touched.append(path)
            path.unlink()
        return tuple(published)
    except Exception:
        failed = []
        for path in reversed(list(dict.fromkeys(touched))):
            try:
                if path in backups:
                    os.replace(backups[path], path)
                elif path in created:
                    path.unlink(missing_ok=True)
            except OSError as error:
                failed.append(f"{path}: {error}")
        if failed:
            preserve_backups = True
            raise RuntimeError(f"Compact rollback incomplete; backups retained at {backup_dir}: {failed}")
        raise
    finally:
        if not preserve_backups:
            shutil.rmtree(backup_dir)


def compact_run(root: str | Path,
                *,
                choose: Callable[[PreflightReport], str],
                confirm: Callable[[CompactionPlan], bool],
                rebuild: Callable[[PreflightReport], None] | None = None,
                publisher: Callable[[CompactionPlan], tuple[Path, ...]] | None = None,
                ) -> tuple[Path, ...]:
    """
    Preview conflicts, optionally rebuild, then confirm the exact deletion plan.
    """
    root = Path(root).expanduser().resolve()
    require_current_run(root)
    states = active_states(discover_saved_states(root))
    if states and all(state.compacted for state in states):
        return ()
    config = run_config(root)
    report = inspect_run(root, config)
    compacted_folders = {state.workdir for state in states if state.compacted}
    report = replace(report,
                     records=tuple(record for record in report.records if record.path.parent not in compacted_folders),
                     )
    report = replace(report, overwritten=(), disabled_steps=(), affected=downstream_steps(
        record.step for record in report.conflicts if record.step))
    accepted = False
    if report.needs_decision:
        decision = choose(report)
        if decision == "cancel":
            raise PipelineCancelled("Compact cancelled at conflict review; no files compacted.")
        if decision == "rebuild":
            if rebuild is None:
                raise PreflightRequired(report)
            rebuild(report)
            report = inspect_run(root, run_config(root))
            if report.conflicts:
                raise ValueError("Conflicts remain after rebuilding. Review the results before compacting.\n" + report.describe())
        elif decision == "continue" and not report.legacy:
            accepted = True
        else:
            raise ValueError("Earlier-version results cannot be compacted without rebuilding.")
    plan = plan_compaction(root, conflicts_accepted=accepted)
    if not confirm(plan):
        raise PipelineCancelled("Compact cancelled at file preview; no files compacted. Any completed rebuild has been kept.")
    return (publisher or apply_compaction)(plan)
