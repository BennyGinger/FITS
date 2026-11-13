"""Contextual file management with explicit previews and responsive writes."""

from __future__ import annotations
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any
from pathlib import Path
from PySide6.QtCore import QItemSelectionModel, QSize, Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from fisch.gui.dialogs import size_resizable_dialog
from fisch.gui.channel_labels.panel import ChannelLabelsPanel
from fisch.gui.help.dialog import info_button, show_help
from fisch.workflows.file_management.relocation import PortablePlan
from fisch.workflows.file_management.rebuild import ProcessingPlan, geometry_reviews, accept_reviewed_geometry, full_rebuild_folders, rebuild_analysis_tables
from fisch.workflows.file_management.compaction import run_config
from fisch.workflows.checks.artifacts import inspect_run
from fisch.workflows.checks.locations import LocationReport, inspect_locations
from fisch.settings.loader import run_settings_path
from fisch.workflows.file_management import api
from fisch.workflows.file_management.history import Snapshot, snapshots, restore_history, delete_history
from fisch.workflows.checks.compatibility import inspect_run_compatibility
from fisch.gui.file_management.compaction import run_compaction_ui
from fisch.workflows.checks.models import PreflightReport, RunCompatibility
from fisch.workflows.runtime.errors import PipelineCancelled
from fisch.gui.file_management.tasks import run_file_task
from fisch.gui.file_preview.widget import FilePreviewWidget
from fisch.gui.file_preview.changes import FileChangesWidget
from fisch.gui.file_preview.processing import processing_groups
from fisch.gui.file_preview.portable import portable_changes
from fisch.gui.file_preview.backups import restoration_changes
from fisch.gui.file_preview.review import review_tabs, size_file_review
from fisch.gui.file_preview.migration import MigrationPreviewWidget
from fisch.gui.file_management.guidance import FileGuidanceWidget, file_guidance
from fisch.gui.file_management.reset import confirm_reset
from fisch.gui.file_management.icons import restore_icon
from fisch.workflows.file_management.reset import plan_reset


class _FileManagerDialog(QDialog):
    """Keep inline rename workers alive until their file operation finishes."""

    channel_editor: ChannelLabelsPanel | None = None
    _pending_result: int | None = None

    def done(self, result: int) -> None:
        """
        Block Escape, close, and maintenance actions while a rename is running.
        """
        if self.channel_editor is not None and self.channel_editor.is_busy:
            if not self.channel_editor.is_saving:
                self._pending_result = result
            return
        if self.channel_editor is not None:
            self.channel_editor.finish_session()
        super().done(result)


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
    dialog.setWindowTitle('Review migration to FIScH 5')
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
    required = any(state.compacted and not state.excluded for state in plan.states)
    if required:
        rebuild.setChecked(True)
        rebuild.setEnabled(False)
        rebuild.setText('Rebuild required: legacy compacted experiments must be reconstructed from originals')
        previews.show_rebuild(True)
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
    from fisch.cli.interactive import run_pipeline_cli
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
        _set_notice(notice, 'Migrate this run to FIScH 5 before compacting its experiments.')
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
    picked = tuple(entries) if action == 'delete_all' else tuple(entries[index.row()] for index in history.selectedIndexes())
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
    if action == 'delete_all':
        text = (f'Delete all {len(picked)} backups shown in this list '
                f'(approximately {sum(entry.size for entry in picked)/1024**2:.1f} MiB)? '
                'Current results, original acquisitions and backups outside this list are preserved.')
    text += '\n\n' + '\n'.join(str(path) for entry in picked for path in entry.files)
    if not confirm_files('Review backups',
                         text,
                         parent,
                         'Restore backup' if action == 'restore' else
                         'Delete all listed backups' if action == 'delete_all' else 'Delete selected backups',
                         preview=FileChangesWidget(restoration_changes(root, picked[0])) if action == 'restore' else None,
                         ):
        return None
    if action == 'restore':
        return lambda: run_file_task(lambda: restore_history(root, picked[0]), parent.parentWidget())
    return lambda: run_file_task(lambda: delete_history(root, picked), parent.parentWidget())


def _backup_row(history: QListWidget, index: int, title: str, choose: Callable[[str], None]) -> QWidget:
    """
    Display one backup with restore and delete actions bound to that row.
    """
    row = QWidget()
    row.setAutoFillBackground(True)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(6, 3, 3, 3)
    label = QLabel(title)
    label.setToolTip(title)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout.addWidget(label, 1)

    def _choose_row(action: str) -> None:
        """
        Target only the backup beside the clicked icon, regardless of prior selection.
        """
        history.setCurrentRow(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        choose(action)

    restore = QPushButton()
    restore.setObjectName(f'backup_restore_{index}')
    restore.setIcon(restore_icon(history.palette().color(QPalette.ColorRole.Text)))
    restore.setIconSize(QSize(22, 22))
    restore.setAccessibleName('Restore this backup')
    restore.setToolTip(f'Restore this backup and retain the current version.\n{title}')
    delete = QPushButton('🗑')
    delete.setObjectName(f'backup_delete_{index}')
    delete.setAccessibleName('Delete this backup')
    delete.setToolTip(f'Delete only this backup. Current experiment files are kept.\n{title}')
    for button, action in ((restore, 'restore'), (delete, 'delete')):
        button.setFixedSize(28, 28)
        button.setProperty('compact_action', True)
        button.clicked.connect(lambda checked=False, action=action: _choose_row(action))
        layout.addWidget(button)
    return row


def _history_panel(entries: Sequence[Snapshot],
                   root: Path,
                   choose: Callable[[str], None],
                   ) -> tuple[QGroupBox, QListWidget, QLabel]:
    """
    List backups with row actions and an explicit delete-all action in the status row.
    """
    group = QGroupBox('Manage backups')
    layout = QVBoxLayout(group)
    size = sum(entry.size for entry in entries) / 1024**2
    layout.addWidget(QLabel(f'{len(entries)} backups available · {size:.1f} MiB' if entries else 'No backups available · 0 MiB'))
    instruction = QLabel('Use the restore or bin icon beside a backup to act on that version. Hover over a backup to read its full details.')
    instruction.setWordWrap(True)
    instruction.setVisible(bool(entries))
    layout.addWidget(instruction)
    history = QListWidget()
    history.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    history.setToolTip(instruction.text())
    rows: list[QWidget] = []
    for index, entry in enumerate(entries):
        label = 'Whole run' if entry.whole_run else str(entry.series.relative_to(root))
        title = f'{label} / {entry.directory.name} — {entry.reason} — {entry.size / 1024**2:.1f} MiB'
        item = QListWidgetItem(title, history)
        item.setToolTip(title)
        row = _backup_row(history, index, title, choose)
        item.setSizeHint(row.sizeHint())
        history.setItemWidget(item, row)
        row.setBackgroundRole(QPalette.ColorRole.Base)
        rows.append(row)
    history.setVisible(bool(entries))
    layout.addWidget(history)
    bottom = QHBoxLayout()
    selection = QLabel()
    selection.setObjectName('backup_selection_status')
    selection.setWordWrap(True)
    selection.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    bottom.addWidget(selection, 1)
    delete_all = QPushButton('🗑 Delete all backups…')
    delete_all.setObjectName('backup_delete_all')
    delete_all.setAccessibleName('Delete all listed backups')
    delete_all.setToolTip('Review deleting every backup shown in this list. Current results, original acquisitions and backups outside this list are kept.')
    delete_all.setEnabled(bool(entries))
    delete_all.clicked.connect(lambda: choose('delete_all'))
    bottom.addWidget(delete_all, 0, Qt.AlignmentFlag.AlignRight)
    layout.addLayout(bottom)

    def _selection_changed() -> None:
        """
        Keep the short selection status and row colours in sync with the list.
        """
        count = len(history.selectedIndexes())
        noun = 'backup' if count == 1 else 'backups'
        selection.setText(f'{count} {noun} selected.' if count else 'No backup selected.' if entries else 'No backups available.')
        for index, row in enumerate(rows):
            item = history.item(index)
            selected = item is not None and item.isSelected()
            palette = history.palette()
            palette.setColor(QPalette.ColorRole.Base, palette.color(QPalette.ColorRole.Highlight if selected else QPalette.ColorRole.Base))
            palette.setColor(QPalette.ColorRole.WindowText, palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text))
            row.setPalette(palette)

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
        return dict.fromkeys(actions, 'Migrate this run to FIScH 5 first.')
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
        return ('Migrate to FIScH 5…', 'migrate',
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
    group = QGroupBox()
    group.setObjectName("experiment_files")
    layout = QVBoxLayout(group)
    header = QHBoxLayout()
    header.addWidget(QLabel("Experiment files"))
    header.addStretch()
    help_button = info_button()
    help_button.clicked.connect(lambda: show_help(group.window(), title="Manage files", gui="Manage files",
                                                 guide_page="tools/manage_files.md"))
    header.addWidget(help_button)
    layout.addLayout(header)
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
                 labels_saved: Callable[[dict[str, str]], None] | None = None,
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
    dialog = _FileManagerDialog(parent)
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
    renamed = False

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
    label_group = QGroupBox("Channel labels")
    label_layout = QVBoxLayout(label_group)
    if status.outdated:
        label_layout.addWidget(QLabel("Migrate this read-only run before changing its channel labels."))
    else:
        editor = ChannelLabelsPanel(root)
        dialog.channel_editor = editor
        label_layout.addWidget(editor)

        def _labels_saved(mapping: dict[str, str]) -> None:
            """
            Remember inline changes and update the caller's in-memory settings.
            """
            nonlocal renamed
            renamed = True
            if labels_saved is not None:
                labels_saved(mapping)

        def _label_busy(busy: bool) -> None:
            """
            Prevent file-management actions from racing an inline rename.
            """
            writing = busy and editor.is_saving
            for index in range(content_layout.count()):
                item = content_layout.itemAt(index)
                widget = item.widget() if item is not None else None
                if widget is not None and widget is not label_group:
                    widget.setEnabled(not writing)
            close.setEnabled(not writing)
            if not busy and dialog._pending_result is not None:
                result, dialog._pending_result = dialog._pending_result, None
                QTimer.singleShot(0, dialog, partial(dialog.done, result))
            QTimer.singleShot(0, dialog, partial(_fit_manager_height, dialog))

        editor.labels_saved.connect(_labels_saved)
        editor.busy_changed.connect(_label_busy)
    content_layout.addWidget(label_group)
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
                               'All FIScH results and backup history are removed. Confirmation is required.')
        reset_button.clicked.connect(lambda: choose('reset'))
        reset_layout.addWidget(reset_button)
        content_layout.addWidget(reset_group)
    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.setObjectName('file_management_close')
    close.rejected.connect(dialog.reject)
    layout.addWidget(close)
    for button in dialog.findChildren(QPushButton):
        if not button.property('compact_action'):
            button.setMinimumHeight(38)
    size_resizable_dialog(dialog, 960, 300)
    _fit_manager_height(dialog)
    dialog.exec()
    action = pending[0]
    if action is None:
        return renamed
    try:
        action()
    except PipelineCancelled:
        return False
    return True
