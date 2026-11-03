"""Contextual file management with explicit previews and responsive writes."""

from __future__ import annotations
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFrame, QGroupBox, QLabel, QListWidget, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from fits.gui.dialogs import size_resizable_dialog
from fits.workflows.file_management.relocation import PortablePlan
from fits.workflows.file_management.rebuild import ProcessingPlan, geometry_reviews, accept_reviewed_geometry
from fits.workflows.file_management.compaction import run_config
from fits.workflows.checks.artifacts import inspect_run
from fits.settings.loader import run_settings_path
from fits.workflows.file_management import api
from fits.workflows.file_management.history import Snapshot, snapshots, restore_history, delete_history
from fits.workflows.checks.compatibility import inspect_run_compatibility
from fits.gui.file_management.compaction import run_compaction_ui
from fits.workflows.checks.models import PreflightReport
from fits.workflows.runtime.errors import PipelineCancelled
from fits.gui.file_management.tasks import run_file_task


def _set_notice(notice: QLabel, text: str) -> None:
    """
    Show actionable feedback without reserving an empty status area.
    """
    notice.setText(text)
    notice.setVisible(bool(text))


def confirm_files(title: str, text: str, parent: QWidget | None = None, action: str = 'Apply listed changes') -> bool:
    """
    Display a scrollable preview and return whether the listed changes were accepted.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    details = QPlainTextEdit(text)
    details.setReadOnly(True)
    layout.addWidget(details)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    button = buttons.button(QDialogButtonBox.StandardButton.Ok)
    if button is not None:
        button.setText(action)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    size_resizable_dialog(dialog, 900, 600)
    return dialog.exec() == QDialog.DialogCode.Accepted


def _migration_details(text: str) -> QWidget:
    """
    Build an arrow disclosure with full-height, selectable migration details.
    """
    section = QWidget()
    layout = QVBoxLayout(section)
    layout.setContentsMargins(0, 0, 0, 0)
    toggle = QPushButton('Details ▾')
    toggle.setCheckable(True)
    toggle.setFlat(True)
    toggle.setStyleSheet('text-align: left; color: #b8b8b8; font-style: italic;')
    details = QLabel(text)
    details.setTextFormat(Qt.TextFormat.PlainText)
    details.setWordWrap(True)
    details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
    details.hide()

    def _toggle_details(expanded: bool) -> None:
        """
        Reveal the description and update the disclosure arrow.
        """
        details.setVisible(expanded)
        toggle.setText('Details ▴' if expanded else 'Details ▾')

    toggle.toggled.connect(_toggle_details)
    layout.addWidget(toggle)
    layout.addWidget(details)
    return section


def confirm_migration(plan: PortablePlan, parent: QWidget | None = None) -> bool | None:
    """
    None cancels; False migrates only; True also requests a complete rebuild.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle('Review migration to FITS 4')
    layout = QVBoxLayout(dialog)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    explanation = QLabel('Migration updates folders, metadata and paths/tags while preserving image pixels and measurements. A complete original run copy is retained under backup so its folders, files and metadata can be restored. Historical input lineage cannot be verified and will be recorded as unavailable.')
    explanation.setWordWrap(True)
    content_layout.addWidget(explanation)
    content_layout.addWidget(_migration_details(plan.describe()))
    content_layout.addSpacing(12)
    rebuild = QCheckBox('Also rebuild all experiment results from the original acquisition')
    rebuild.setToolTip('Optional full processing: recreate intermediate files, final images, masks and measurements. This can take a long time and change results. A backup is retained first.')
    content_layout.addWidget(rebuild)
    warning = QLabel('Full rebuilding is optional and can take a long time. Final results may change slightly, even with the same settings; different processing versions or settings can also change results. A backup is retained before any existing results are replaced.')
    warning.setStyleSheet('color: #f0b66a;')
    warning.setWordWrap(True)
    content_layout.addWidget(warning)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Migrate')
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    size_resizable_dialog(dialog, 840, 340)
    return rebuild.isChecked() if dialog.exec() == QDialog.DialogCode.Accepted else None


def _run_cli_processing(root: Path, plan: ProcessingPlan) -> None:
    """
    Start the CLI-owned interactive runner when no main-window callback exists.
    """
    # The runner loads mask/viewer windows; import it only for standalone use.
    from fits.cli.interactive import run_pipeline_cli
    run_pipeline_cli(run_settings_path(root), maintenance=plan, show_completion=False)


def _migration_action(root: Path,
                      parent: QWidget,
                      notice: QLabel,
                      run_processing: Callable[[ProcessingPlan], None],
                      ) -> Callable[[], Any] | None:
    """
    Review migration separately from optional numerical reconstruction.
    """
    plan = api.plan_migration(root)
    if plan is None:
        _set_notice(notice, 'There are no files to migrate. This run already uses the current format and folder structure.')
        return None
    rebuild = confirm_migration(plan, parent)
    if rebuild is None:
        return None

    def apply() -> None:
        """
        Migrate, then run the full rebuild already accepted in the migration dialog.
        """
        run_file_task(lambda: api.migrate(plan), parent.parentWidget())
        if rebuild:
            processing = api.plan_full_rebuild(root)
            if processing is not None:
                api.update_downstream(processing, run_processing)
    return apply


def _rebuild_action(root: Path,
                    parent: QWidget | None,
                    notice: QLabel,
                    run_processing: Callable[[ProcessingPlan], None],
                    ) -> Callable[[], Any] | None:
    """
    Review full processing, with a backup and explicit time/result-change warnings.
    """
    plan = api.plan_full_rebuild(root)
    if plan is None:
        _set_notice(notice, 'There are no processed experiments to rebuild. Convert your inputs first.')
        return None
    if not confirm_files('Review full experiment rebuild',
                         plan.describe(),
                         parent,
                         'Rebuild all experiment results',
                         ):
        return None
    return lambda: api.update_downstream(plan, run_processing)


def _update_action(root: Path, parent: QWidget, notice: QLabel) -> Callable[[], Any] | None:
    """
    Review path/tag changes without launching processing.
    """
    plan = api.plan_update(root)
    if plan is None:
        _set_notice(notice, 'There are no processed experiments to update. Convert your inputs first.')
        return None
    if not confirm_files('Update run paths and condition tags', plan.describe(), parent):
        return None
    return lambda: run_file_task(lambda: api.update(plan), parent.parentWidget())


def _downstream_action(root: Path,
                       parent: QWidget,
                       notice: QLabel,
                       reviews: Sequence[tuple[Path, Path]],
                       run_processing: Callable[[ProcessingPlan], None],
                       ) -> Callable[[], Any] | None:
    """
    Review actual revision conflicts or explain why no processing is needed.
    """
    plan = api.plan_downstream_update(root)
    if plan is None:
        _set_notice(notice, 'REF/ROI drawings need alignment review. Inspect them in the viewer and use Accept reviewed alignment below. There are no outdated results to rebuild automatically.' if reviews else
                       'There are no outdated results to rebuild. No missing inputs or changed inputs were found.')
        return None
    if not confirm_files('Review rebuilding outdated results', plan.describe(), parent, 'Rebuild listed results'):
        return None
    return lambda: api.update_downstream(plan, run_processing)


def _geometry_action(root: Path, parent: QWidget, reviews: Sequence[tuple[Path, Path]]) -> Callable[[], Any] | None:
    """
    Obtain explicit acceptance of drawings already checked in the viewer.
    """
    text = ('First inspect these drawings against the current images in Image / Mask Viewer. '
            'Accept only if they align. Pixels are preserved and your acceptance of the new geometry is recorded.\n\n' +
            '\n'.join(f'{path}\n  image: {image}' for path, image in reviews))
    if not confirm_files('Confirm reviewed alignment', text, parent, 'Accept reviewed alignment'):
        return None
    return lambda: run_file_task(lambda: accept_reviewed_geometry(root, reviews), parent.parentWidget())


def _compact_action(root: Path,
                    parent: QWidget,
                    notice: QLabel,
                    run_processing: Callable[[ProcessingPlan], None],
                    ) -> Callable[[], Any] | None:
    """
    Open reviewed compaction separately from backup creation and management.
    """
    if inspect_run_compatibility(root).outdated:
        _set_notice(notice, 'Migrate this run to FITS 4 before compacting its experiments.')
        return None

    def _rebuild(_report: PreflightReport) -> None:
        """
        Use the normal reviewed numerical plan when compaction requires rebuilding.
        """
        plan = api.plan_downstream_update(root)
        if plan is not None:
            api.update_downstream(plan, run_processing)

    return lambda: run_compaction_ui(root, parent.parentWidget(), rebuild=_rebuild)


def _history_action(root: Path,
                    parent: QWidget,
                    notice: QLabel,
                    history: QListWidget,
                    entries: Sequence[Snapshot],
                    action: str,
                    ) -> Callable[[], Any] | None:
    """
    Review restoration or deletion of the selected retained revisions.
    """
    picked = tuple(entries[index.row()] for index in history.selectedIndexes())
    if not picked:
        _set_notice(notice, 'Select a backup in the list above first.' if entries else 'There are no backups to restore or delete.')
        if entries:
            history.setFocus()
        return None
    if action == 'restore' and len(picked) != 1:
        _set_notice(notice, 'Select one backup to restore.')
        return None
    text = ('Restore the selected experiment results and state. Current results will be retained as another backup; master tables will be invalidated.' if action == 'restore' else
            f'Delete only these selected backups (approximately {sum(entry.size for entry in picked)/1024**2:.1f} MiB). Current results and original acquisitions are preserved.')
    if action == 'restore' and picked[0].whole_run:
        text = ('Restore the complete run folder, including its original structure, files, metadata, settings and tables. '
                'This affects the whole run, regardless of the selected experiment. '
                'The current run will be retained as another backup before restoring.')
    text += '\n\n' + '\n'.join(str(path) for entry in picked for path in entry.files)
    if not confirm_files('Review backups',
                         text,
                         parent,
                         'Restore backup' if action == 'restore' else 'Delete selected backups',
                         ):
        return None
    if action == 'restore':
        return lambda: run_file_task(lambda: restore_history(root, picked[0]), parent.parentWidget())
    return lambda: run_file_task(lambda: delete_history(root, picked), parent.parentWidget())


def _history_panel(entries: Sequence[Snapshot],
                   root: Path,
                   choose: Callable[[str], None],
                   ) -> tuple[QGroupBox, QListWidget, QLabel]:
    """
    Build the history size summary, revision selection and restore/delete buttons.
    """
    group = QGroupBox('Manage backups')
    layout = QVBoxLayout(group)
    size = sum(entry.size for entry in entries) / 1024**2
    layout.addWidget(QLabel(f'{len(entries)} backups available · {size:.1f} MiB' if entries else 'No backups available · 0 MiB'))
    instruction = QLabel('Select one backup to restore, or one or more to delete. Use Ctrl+click to select multiple backups.')
    instruction.setWordWrap(True)
    instruction.setVisible(bool(entries))
    layout.addWidget(instruction)
    history = QListWidget()
    history.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    history.setToolTip(instruction.text())
    for entry in entries:
        label = 'Whole run' if entry.whole_run else str(entry.series.relative_to(root))
        history.addItem(f'{label} / {entry.directory.name} — {entry.reason} — {entry.size / 1024**2:.1f} MiB')
    history.setVisible(bool(entries))
    layout.addWidget(history)
    selection = QLabel()
    selection.setWordWrap(True)
    selection.setVisible(bool(entries))
    layout.addWidget(selection)

    def _selection_changed() -> None:
        """
        Show the backup selection used by the restore and delete actions.
        """
        count = len(history.selectedIndexes())
        noun = 'backup' if count == 1 else 'backups'
        selection.setText(f'{count} {noun} selected.' if count else 'No backup selected. Choose a backup in the list before continuing.')

    history.itemSelectionChanged.connect(_selection_changed)
    _selection_changed()
    for title, action, tooltip in (
        ('Restore selected backup…', 'restore', 'Restore the selected saved version and retain the current version. Whole-run backups also restore its original folders and metadata.'),
        ('Delete selected backups…', 'delete', 'Permanently delete only the selected backups to free disk space. Current experiment files are kept.')):
        button = QPushButton(title)
        button.setToolTip(tooltip)
        button.clicked.connect(lambda checked=False, action=action: choose(action))
        layout.addWidget(button)
    return group, history, selection


def manage_files(root: str | Path,
                 selected: Path | None = None,
                 parent: QWidget | None = None,
                 run_processing: Callable[[ProcessingPlan], None] | None = None,
                 ) -> bool:
    """
    Present run-wide file actions and execute only an accepted review after closing.
    """
    root = Path(root).resolve()
    status = inspect_run_compatibility(root)
    entries = snapshots(root, selected)
    reviews = geometry_reviews(root)
    processing_runner = run_processing or partial(_run_cli_processing, root)
    dialog = QDialog(parent)
    dialog.setWindowTitle('Manage experiment files')
    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    notice = QLabel(dialog)
    notice.setWordWrap(True)
    notice.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    notice.hide()
    if status.outdated:
        _set_notice(notice, 'This run needs an upgrade to FITS v4. You can keep viewing its files read-only, or migrate without rerunning processing.')
    elif inspect_run(root, run_config(root), for_execution=False).conflicts:
        _set_notice(notice, 'This run has outdated results because their inputs changed or are missing. Choose Rebuild outdated results to review what needs to run again. Existing files remain viewable.')
    layout.addWidget(notice)
    pending: list[Callable[[], Any] | None] = [None]

    def choose(action: str) -> None:
        """
        Review the requested action, keeping explanations inside the manager.
        """
        try:
            if action == 'migrate':
                pending[0] = _migration_action(root, dialog, notice, processing_runner)
            elif action == 'rebuild':
                pending[0] = _rebuild_action(root, dialog, notice, processing_runner)
            elif action == 'update':
                pending[0] = _update_action(root, dialog, notice)
            elif action == 'downstream':
                pending[0] = _downstream_action(root, dialog, notice, reviews, processing_runner)
            elif action == 'geometry':
                pending[0] = _geometry_action(root, dialog, reviews)
            elif action == 'compact':
                pending[0] = _compact_action(root, dialog, notice, processing_runner)
            else:
                pending[0] = _history_action(root, dialog, backup_notice, history, entries, action)
            if pending[0] is not None:
                dialog.accept()
        except Exception as error:
            _set_notice(notice, str(error))

    if status.outdated:
        primary_action = ('Migrate to FITS 4…', 'migrate',
                          'Migrate folders and metadata without rerunning processing. Optionally rebuild all results; this can take a long time and may change results. Backups are retained.')
    else:
        primary_action = ('Rebuild all experiment results…', 'rebuild',
                          'Rebuild the complete workflow from original acquisitions, including final images, masks and measurements. '
                          'This can take a long time and may change results. A backup is retained first.')
    active_group = QGroupBox('Experiment files')
    active_layout = QVBoxLayout(active_group)
    layout.addWidget(active_group)
    for title, action, tooltip in (
        primary_action,
        ('Update paths and condition tags…', 'update', 'Refresh paths, identifiers, condition tags and master tables throughout the run; preserve measurements and retain a restorable run backup.'),
        ('Rebuild outdated results…', 'downstream', 'Review results affected by changed or missing inputs, retain a backup before replacing existing results, then rerun the affected processing.')):
        button = QPushButton(title)
        button.setToolTip(tooltip)
        button.clicked.connect(lambda checked=False, action=action: choose(action))
        active_layout.addWidget(button)
    if reviews:
        review = QPushButton('Accept reviewed REF/ROI alignment…')
        review.setToolTip('Record that you checked these drawings against the current registration. Drawing pixels are kept.')
        review.clicked.connect(lambda: choose('geometry'))
        active_layout.addWidget(review)
    active_layout.addSpacing(12)
    compact = QPushButton('Compact experiment…')
    compact.setToolTip('Free disk space by removing intermediate files and caches. Keep original acquisitions, final images and masks, REF/ROI masks, measurements and reports. No persistent backup is created.')
    compact.clicked.connect(lambda: choose('compact'))
    active_layout.addWidget(compact)
    group, history, backup_notice = _history_panel(entries, root, choose)
    layout.addWidget(group)
    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.rejected.connect(dialog.reject)
    layout.addWidget(close)
    for button in dialog.findChildren(QPushButton):
        button.setMinimumHeight(38)
    size_resizable_dialog(dialog, 960, 720)
    dialog.exec()
    action = pending[0]
    if action is None:
        return False
    try:
        action()
    except PipelineCancelled:
        return False
    return True
