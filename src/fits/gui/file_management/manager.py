"""Contextual file management with explicit previews and responsive writes."""

from __future__ import annotations
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QListWidget, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget
from fits.gui.dialogs import size_resizable_dialog
from fits.workflows.file_management.relocation import PortablePlan
from fits.workflows.file_management.rebuild import ProcessingPlan, geometry_reviews, accept_reviewed_geometry, full_rebuild_folders, rebuild_analysis_tables
from fits.workflows.file_management.compaction import run_config
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.locations import LocationReport, inspect_locations
from fits.settings.loader import run_settings_path
from fits.workflows.file_management import api
from fits.workflows.file_management.history import Snapshot, snapshots, restore_history, delete_history
from fits.workflows.checks.compatibility import inspect_run_compatibility
from fits.gui.file_management.compaction import run_compaction_ui
from fits.workflows.checks.models import PreflightReport, RunCompatibility
from fits.workflows.runtime.errors import PipelineCancelled
from fits.gui.file_management.tasks import run_file_task
from fits.gui.file_preview.widget import FilePreviewWidget
from fits.gui.file_preview.changes import FileChangesWidget
from fits.gui.file_preview.processing import processing_groups
from fits.gui.file_preview.portable import portable_changes
from fits.gui.file_preview.backups import restoration_changes
from fits.gui.file_preview.review import review_tabs, size_file_review
from fits.gui.file_preview.migration import MigrationPreviewWidget
from fits.gui.file_management.guidance import FileGuidanceWidget, file_guidance
from fits.gui.file_management.reset import confirm_reset
from fits.workflows.file_management.reset import plan_reset


def _fit_manager_height(dialog: QDialog) -> None:
    """
    Fit both columns and the backups section at the dialog's current width.
    """
    layout = dialog.layout()
    assert layout is not None
    layout.invalidate()
    scroll = dialog.findChild(QScrollArea, 'file_management_content')
    assert scroll is not None
    content = scroll.widget()
    assert content is not None
    content_layout = content.layout()
    assert content_layout is not None
    content_layout.invalidate()
    margins = layout.contentsMargins()
    width = dialog.width() - margins.left() - margins.right() - scroll.verticalScrollBar().sizeHint().width()
    height = max(content_layout.minimumSize().height(), content_layout.totalHeightForWidth(width))
    close = dialog.findChild(QDialogButtonBox, 'file_management_close')
    assert close is not None
    height += close.sizeHint().height() + margins.top() + margins.bottom() + layout.spacing()
    size_resizable_dialog(dialog, dialog.width(), height)


def _set_notice(notice: QLabel, text: str) -> None:
    """
    Show actionable feedback without reserving an empty status area.
    """
    notice.setText(text)
    notice.setVisible(bool(text))
    dialog = notice.window()
    if isinstance(dialog, QDialog) and dialog.isVisible():
        _fit_manager_height(dialog)


def confirm_files(title: str,
                  text: str,
                  parent: QWidget | None = None,
                  action: str = 'Apply listed changes',
                  *,
                  preview: QWidget | None = None,
                  ) -> bool:
    """
    Display a scrollable preview and return whether the listed changes were accepted.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    if preview is not None:
        layout.addWidget(review_tabs(preview, text, 'File changes' if isinstance(preview, FileChangesWidget) else 'Run overview'))
    else:
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
    if preview is not None:
        size_file_review(dialog)
    else:
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
    explanation = QLabel('Migration updates folders, metadata, saved paths and condition tags. Pixels and measurements are preserved unless rebuilding is selected. A complete backup is retained first.')
    explanation.setWordWrap(True)
    content_layout.addWidget(explanation)
    previews = MigrationPreviewWidget(plan)
    content_layout.addWidget(previews)
    content_layout.addWidget(_migration_details('Historical input lineage cannot be verified and will be recorded as unavailable.\n\n' + plan.describe()))
    content_layout.addSpacing(12)
    rebuild = QCheckBox('Also rebuild all experiment results from the original acquisition')
    rebuild.setToolTip('Optional full processing: recreate intermediate files, final images, masks and measurements. This can take a long time and change results. A backup is retained first.')
    rebuild.toggled.connect(previews.show_rebuild)
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
    size_file_review(dialog)
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
    report = inspect_run(root, run_config(root), for_execution=False)
    if report.analysis_only_rebuild:
        return lambda: run_file_task(lambda: rebuild_analysis_tables(root), parent,
                                      title='Rebuilding analysis',
                                      message='Combining results from active experiments…',
                                      )
    plan = api.plan_required_rebuild(root)
    if plan is None:
        reviews = geometry_reviews(root)
        if reviews and parent is not None:
            return _geometry_action(root, parent, reviews)
        _set_notice(notice, 'All results are current; no rebuilding is needed.')
        return None
    if not confirm_files('Review required experiment rebuilding',
                         plan.describe(),
                         parent,
                         'Rebuild listed results',
                         preview=FilePreviewWidget(processing_groups(plan), 'Rebuilding can take a long time and may change final results. Existing results are backed up before processing starts.'),
                         ):
        return None
    return lambda: api.update_downstream(plan, run_processing)


def _update_action(root: Path, parent: QWidget, notice: QLabel) -> Callable[[], Any] | None:
    """
    Review path/tag changes without launching processing.
    """
    plan = api.plan_update(root)
    if plan is None:
        _set_notice(notice, 'Saved paths and master-table tags already match this run. Nothing needs updating.')
        return None
    if not confirm_files('Update run paths and condition tags', plan.describe(), parent,
                         preview=FileChangesWidget(portable_changes(plan)),
                         ):
        return None
    return lambda: run_file_task(lambda: api.update(plan), parent.parentWidget())


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
                         preview=FileChangesWidget(restoration_changes(root, picked[0])) if action == 'restore' else None,
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
    buttons: dict[str, QPushButton] = {}

    def _selection_changed() -> None:
        """
        Show the backup selection used by the restore and delete actions.
        """
        count = len(history.selectedIndexes())
        noun = 'backup' if count == 1 else 'backups'
        selection.setText(f'{count} {noun} selected.' if count else 'No backup selected. Choose a backup in the list before continuing.')
        buttons['restore'].setEnabled(count == 1)
        buttons['delete'].setEnabled(count > 0)

    for title, action, tooltip in (
        ('Restore selected backup…', 'restore', 'Restore the selected saved version and retain the current version. Whole-run backups also restore its original folders and metadata.'),
        ('Delete selected backups…', 'delete', 'Permanently delete only the selected backups to free disk space. Current experiment files are kept.')):
        button = QPushButton(title)
        buttons[action] = button
        button.setToolTip(tooltip)
        button.clicked.connect(lambda checked=False, action=action: choose(action))
        layout.addWidget(button)
    history.itemSelectionChanged.connect(_selection_changed)
    _selection_changed()
    return group, history, selection


def _unavailable_actions(status: RunCompatibility,
                          report: PreflightReport | None,
                          locations: LocationReport,
                          reviews: Sequence[tuple[Path, Path]],
                          ) -> dict[str, str]:
    """
    Enable only file actions supported by actual reconstruction or location differences.
    """
    actions = ('rebuild', 'update', 'compact')
    if status.outdated:
        return dict.fromkeys(actions, 'Migrate this run to FITS v4 first.')
    if not status.states:
        unavailable = dict.fromkeys(('rebuild', 'compact'), 'Convert your inputs first; this run has no processed experiments.')
        if not locations.needs_update:
            unavailable['update'] = 'There are no saved location differences to update.'
        return unavailable
    unavailable: dict[str, str] = {}
    full = () if report is not None and report.analysis_only_rebuild else full_rebuild_folders(status.states)
    stale = report is not None and bool(report.outdated_masters or any(
        record.problem and record.step is not None for record in report.records))
    if not full and not stale and not reviews:
        unavailable['rebuild'] = 'All existing results are current. No reconstruction or outdated results need rebuilding.'
    elif any(not state.original_image.is_file() for state in status.states if state.workdir in full):
        unavailable['rebuild'] = 'Restore the missing original acquisitions or update their paths before a full rebuild.'
    if not locations.needs_update:
        unavailable['update'] = 'Saved paths and master-table identities/tags match the current folder structure.'
    if not api.can_compact(status.root):
        unavailable['compact'] = 'No uncompacted compatible image results are available.'
    return unavailable


def _primary_action(status: RunCompatibility, report: PreflightReport | None) -> tuple[str, str, str]:
    """
    Name the single reconstruction action according to the run's actual needs.
    """
    if status.outdated:
        return ('Migrate to FITS 4…', 'migrate',
                'Migrate folders and metadata without rerunning processing. Optionally rebuild all results; '
                'this can take a long time and may change results. Backups are retained.')
    if report is not None and report.analysis_only_rebuild:
        return ('Rebuild analysis…', 'rebuild',
                'Regenerate combined analysis using valid results from active experiments. '
                'Individual measurements and images are preserved.')
    full = full_rebuild_folders(status.states)
    stale_elsewhere = report is not None and any(record.problem and record.step is not None
                                                and record.path.parent not in full for record in report.records)
    title = ('Rebuild required results…' if full and stale_elsewhere else
             'Rebuild all results…' if full else 'Rebuild outdated results…' if report is not None and report.conflicts else
             'Rebuild results…')
    return (title, 'rebuild', 'Review the required rebuilding. Compacted or migrated experiments are rebuilt completely; '
            'other experiments rebuild only outdated results. This can take a long time and may change results. '
            'Existing results are backed up first. REF/ROI alignment can be reviewed when needed.')


def _file_actions_panel(guidance: FileGuidanceWidget,
                        primary_action: tuple[str, str, str],
                        choose: Callable[[str], None],
                        unavailable: dict[str, str],
                        ) -> QGroupBox:
    """
    Place run guidance on the left and applicable file actions on the right.
    """
    group = QGroupBox('Experiment files')
    layout = QVBoxLayout(group)
    layout.addWidget(guidance)
    controls = QWidget()
    controls.setMinimumWidth(320)
    buttons = QVBoxLayout(controls)
    buttons.setContentsMargins(0, 0, 0, 0)
    buttons.setSpacing(10)
    actions = [primary_action,
               ('Update paths and condition tags…', 'update', 'Refresh displaced state references and master-table identifiers and condition tags. Portable per-experiment measurements are preserved; a restorable run backup is retained.')]
    actions.append(('Compact experiment…', 'compact', 'Free disk space by removing intermediate files and caches. Keep original acquisitions, final images and masks, REF/ROI masks, measurements and reports. No persistent backup is created.'))
    for title, action, tooltip in actions:
        if action == 'compact':
            buttons.addSpacing(12)
        button = QPushButton(title)
        reason = unavailable.get(action)
        button.setEnabled(reason is None)
        button.setToolTip(f'{tooltip}\n\nUnavailable: {reason}' if reason else tooltip)
        button.clicked.connect(lambda checked=False, action=action: choose(action))
        buttons.addWidget(button)
    buttons.addStretch()
    guidance.add_controls(controls)
    return group


def manage_files(root: str | Path,
                 selected: Path | None = None,
                 parent: QWidget | None = None,
                 run_processing: Callable[[ProcessingPlan], None] | None = None,
                 reset_run: Callable[[], None] | None = None,
                 input_problem: str = '',
                 input_warning: str = '',
                 ) -> bool:
    """
    Present run-wide file actions and execute only an accepted review after closing.
    """
    root = Path(root).resolve()
    status = inspect_run_compatibility(root)
    report = inspect_run(root, run_config(root), for_execution=False) if not status.outdated else None
    locations = inspect_locations(root, status.states) if not status.outdated else LocationReport()
    entries = snapshots(root, selected)
    reviews = geometry_reviews(root)
    unavailable = _unavailable_actions(status, report, locations, reviews)
    processing_runner = run_processing or partial(_run_cli_processing, root)
    dialog = QDialog(parent)
    dialog.setWindowTitle('Manage experiment files')
    dialog.setStyleSheet('QPushButton:disabled { color: #8a8a8a; background-color: #383838; border-color: #555555; }')
    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    scroll = QScrollArea()
    scroll.setObjectName('file_management_content')
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(12)
    content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    notice = QLabel(dialog)
    guidance = FileGuidanceWidget(file_guidance(status, report, locations, reviews,
                                               input_problem=input_problem, input_warning=input_warning), notice)
    guidance.details_toggled.connect(lambda _expanded: QTimer.singleShot(0, dialog, partial(_fit_manager_height, dialog)))
    pending: list[Callable[[], Any] | None] = [None]

    def choose(action: str) -> None:
        """
        Review the requested action, keeping explanations inside the manager.
        """
        _set_notice(notice, '')
        try:
            if action == 'migrate':
                pending[0] = _migration_action(root, dialog, notice, processing_runner)
            elif action == 'rebuild':
                pending[0] = _rebuild_action(root, dialog, notice, processing_runner)
            elif action == 'update':
                pending[0] = _update_action(root, dialog, notice)
            elif action == 'compact':
                pending[0] = _compact_action(root, dialog, notice, processing_runner)
            elif action == 'reset':
                plan_reset(root)
                if confirm_reset(root, dialog):
                    pending[0] = reset_run
            else:
                pending[0] = _history_action(root, dialog, backup_notice, history, entries, action)
            if pending[0] is not None:
                dialog.accept()
        except Exception as error:
            _set_notice(notice, str(error))

    content_layout.addWidget(_file_actions_panel(guidance, _primary_action(status, report), choose, unavailable))
    group, history, backup_notice = _history_panel(entries, root, choose)
    content_layout.addWidget(group)
    if reset_run is not None:
        reset_group = QGroupBox('Reset to raw inputs')
        reset_group.setObjectName('reset_to_raw')
        reset_group.setStyleSheet('QGroupBox#reset_to_raw { color: #ff5555; }')
        reset_layout = QHBoxLayout(reset_group)
        reset_button = QPushButton('Reset')
        reset_button.setStyleSheet('color: #ff5555;')
        reset_button.setToolTip('Permanently reset the whole run to its original acquisitions. '
                               'All FITS results and backup history are removed. Confirmation is required.')
        reset_button.clicked.connect(lambda: choose('reset'))
        reset_layout.addWidget(reset_button)
        content_layout.addWidget(reset_group)
    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.setObjectName('file_management_close')
    close.rejected.connect(dialog.reject)
    layout.addWidget(close)
    for button in dialog.findChildren(QPushButton):
        button.setMinimumHeight(38)
    size_resizable_dialog(dialog, 960, 300)
    _fit_manager_height(dialog)
    dialog.exec()
    action = pending[0]
    if action is None:
        return False
    try:
        action()
    except PipelineCancelled:
        return False
    return True
