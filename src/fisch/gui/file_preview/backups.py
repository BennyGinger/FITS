"""Folder-level restoration changes, without depicting backups as processing inputs."""

from pathlib import Path

from fisch.environment import constant as cst
from fisch.environment.paths import backups_dir, experiment_state_path, STATE_FILENAME
from fisch.gui.file_preview.models import FileChange
from fisch.workflows.artifacts.branch_masks import is_branch
from fisch.workflows.file_management.history import Snapshot
from fisch.workflows.file_management.run_history import RUN_CONTENTS


def restoration_changes(root: Path, snapshot: Snapshot) -> tuple[FileChange, ...]:
    """
    Explain whole-run exchanges or the actual backed-up series files restored.
    """
    if snapshot.whole_run:
        return (FileChange(root, 'Restore complete run', 'Restore the original folders, files, metadata, settings and tables.', snapshot.directory / RUN_CONTENTS),
                FileChange(backups_dir(root), 'Retain current version', 'The displaced current run is retained as another backup.'))
    changes = [FileChange(snapshot.series / path.name, 'Restore saved result',
                          'Replace the active file with its saved pixels and original metadata.', path)
               for path in snapshot.files if path.name in cst.MANAGED_NAMES or is_branch(path)]
    changes.append(FileChange(experiment_state_path(snapshot.series), 'Restore saved state',
                              'Restore the matching experiment state.', snapshot.directory / STATE_FILENAME))
    changes.append(FileChange(snapshot.directory.parent, 'Retain current version', 'Current experiment results are retained as another backup. Run master tables are invalidated.'))
    return tuple(changes)
