"""Preview migration moves and path/tag updates from the reviewed portable plan."""

from pathlib import Path

from fisch.environment import constant as cst
from fisch.environment.paths import experiment_state_path
from fisch.gui.file_preview.models import FileChange, PreviewFile, PreviewGroup, file_stage, file_title
from fisch.workflows.file_management.relocation import PortablePlan
from fisch.workflows.experiments import discover_saved_states
from fisch.settings.loader import run_settings_path


def relocated_path(path: Path, plan: PortablePlan) -> Path:
    """
    Apply the ordered directory/file moves recorded in the executable plan.
    """
    for source, target in plan.moves:
        if path == source or source in path.parents:
            path = target / path.relative_to(source)
    return path


def _series_sources(plan: PortablePlan, old: Path) -> tuple[Path, ...]:
    """
    Select actual scientific files watched by this series' relocation plan.
    """
    return tuple(path for path, _, _ in plan.fingerprints if path.parent == old
                 and (path.name in cst.MANAGED_NAMES or path.match(cst.REFERENCE_TEMPLATE.format(label='*'))
                      or path.match(cst.ROI_TEMPLATE.format(label='*'))))


def portable_groups(plan: PortablePlan) -> tuple[PreviewGroup, ...]:
    """
    Show preserved files at their proposed destinations, with explicit rename labels.
    """
    groups = []
    watched = [path for path, _, _ in plan.fingerprints]
    for state, (old, new) in zip(plan.states, plan.series_moves, strict=True):
        originals = [path for path in watched if relocated_path(path, plan) == state.original_image]
        files = []
        for source in dict.fromkeys([*originals, *_series_sources(plan, old)]):
            target = relocated_path(source, plan)
            action = 'rename' if source.name != target.name else 'move' if source != target else 'update' if plan.migrate else 'keep'
            detail = ('Pixels and measurement values are preserved. Metadata is migrated to FIScH 5.' if plan.migrate
                      else 'Preserved; only its reviewed location changes.')
            if source in originals:
                detail = 'The original acquisition is preserved; only its reviewed location changes.'
            files.append(PreviewFile(target, 'Original' if source in originals else file_title(target), action, detail,
                                     source if source != target else None, -1 if source in originals else file_stage(target)))
        groups.append(PreviewGroup(new, tuple(files)))
    return tuple(groups)


def portable_changes(plan: PortablePlan) -> tuple[FileChange, ...]:
    """
    List file operations and affected metadata/tables without reading measurement arrays.
    """
    if plan.locations is not None:
        changes = [FileChange(issue.path, 'Update paths and tags', issue.reason) for issue in plan.locations.issues]
        changes.append(FileChange(plan.root / '.pipeline' / 'backup', 'Retain backup',
                                  'Retain a complete run snapshot before updating saved references or master tables.'))
        return tuple(changes)
    changes: list[FileChange] = []
    watched = {path for path, _, _ in plan.fingerprints}
    available = {relocated_path(path, plan) for path in watched}
    for source, target in plan.moves:
        changes.append(FileChange(target, 'Rename' if source.name != target.name else 'Move',
                                  'Move the existing file or directory; preserve scientific values.', source))
    for state, (old, _) in zip(plan.states, plan.series_moves, strict=True):
        changes.append(FileChange(experiment_state_path(state.workdir, acquisition=state.original_image.parent),
                                  'Update state', 'Update experiment/artifact paths and saved workflow state.'))
        description = (f'Set portable experiment_id → {state.portable_experiment_id}. '
                       'Refresh relative path columns and metadata; condition tags belong only to the master table. '
                       'Preserve numerical measurements.')
        for name in (cst.QUANTI_NAME, cst.DISTANCE_PROFILE_NAME):
            path = state.workdir / name
            if path in available:
                changes.append(FileChange(path, 'Update paths and tags', description))
        for source in _series_sources(plan, old):
            target = relocated_path(source, plan)
            if target.suffix.lower() in ('.tif', '.tiff') and target.name not in cst.COMPARTMENT_MASK_NAMES:
                changes.append(FileChange(target, 'Migrate metadata' if plan.migrate else 'Check path references',
                                          'Write FIScH 5 metadata; preserve pixels.' if plan.migrate else
                                          'Rewrite embedded input paths only if their references change. Pixels and revision timestamps are preserved.'))
    if not plan.rebuild:
        states = discover_saved_states(plan.root)
        for kind, name in cst.MASTER_TABLES:
            if any(state.workdir / (cst.QUANTI_NAME if kind == cst.ARTI_QUANTI else cst.DISTANCE_PROFILE_NAME) in available
                   for state in plan.states) or any((path := state.artifact(kind)) is not None and path.is_file() for state in states):
                changes.append(FileChange(plan.root / name, 'Regenerate master table',
                                          'Combine existing experiment measurements with current experiment IDs, paths and condition tags. No quantification is rerun.'))
    settings = run_settings_path(plan.root)
    if settings.is_file():
        changes.append(FileChange(settings, 'Check settings paths', 'Update the run directory and run-owned settings paths if changed.'))
    changes.append(FileChange(plan.root / '.pipeline' / 'backup', 'Retain backup',
                              'A complete original run snapshot is retained before applying these changes.'))
    return tuple(changes)
