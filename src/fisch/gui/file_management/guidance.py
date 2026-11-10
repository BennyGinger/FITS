"""Plain-language file status, next actions and technical details for Manage files."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QPlainTextEdit, QToolButton, QSizePolicy, QVBoxLayout, QWidget

from fisch.workflows.checks.locations import LocationReport
from fisch.workflows.checks.models import PreflightReport, RunCompatibility
from fisch.workflows.file_management.rebuild import full_rebuild_folders


@dataclass(frozen=True)
class FileGuidance:
    """
    Keep short explanations separate from the complete affected-file report.
    """

    summary: str
    next_steps: str
    details: str


def _processing_messages(report: PreflightReport) -> tuple[str, str]:
    """
    Distinguish refreshing master tables from recalculating individual results.
    """
    if report.analysis_only_rebuild:
        return ('The master tables are out of date. They no longer match the experiments or results included in this run.',
                'Rebuild analysis would combine the currently included experiments into new master tables. '
                'It would reuse existing images and individual measurements.')
    return ('Some results use older inputs, different settings, or files that are now missing.',
            'Rebuild outdated results would recalculate the affected files and their downstream results. '
            'Existing versions would be backed up first. This could take time and change the results.')


def _technical_details(status: RunCompatibility,
                       report: PreflightReport | None,
                       locations: LocationReport,
                       reviews: Sequence[tuple[Path, Path]],
                       ) -> str:
    """
    List affected files and reasons using the existing read-only checker reports.
    """
    excluded = sum(state.excluded for state in status.states)
    experiments = f'{len(status.states)} experiment' + ('' if len(status.states) == 1 else 's')
    files = f'{len(status.files)} result file' + ('' if len(status.files) == 1 else 's')
    lines = [f'{experiments} · {excluded} excluded · {files}']
    if status.problems:
        lines.append(status.describe())
    if report is not None and (report.conflicts or report.outdated_masters):
        lines.append(report.describe())
    if locations.needs_update:
        lines.append(locations.describe())
    full = full_rebuild_folders(status.states)
    if full:
        lines.append('Experiments available for complete reconstruction:\n' + '\n'.join(map(str, full)))
    if reviews:
        lines.append('REF/ROI drawings to check against the current images:\n' + '\n'.join(
            f'{path}\n  Current image: {image}' for path, image in reviews))
    return '\n\n'.join(lines)


def file_guidance(status: RunCompatibility,
                  report: PreflightReport | None,
                  locations: LocationReport,
                  reviews: Sequence[tuple[Path, Path]] = (),
                  *,
                  input_problem: str = '',
                  input_warning: str = '',
                  ) -> FileGuidance:
    """
    Explain common issues in everyday terms while retaining every checker detail.
    """
    summaries: list[str] = []
    actions: list[str] = []
    if input_problem:
        summaries.append('Some input files need attention before conversion can run.')
        actions.append('Check the input files and channel settings listed in Details before converting.')
    if status.outdated:
        summaries.append('These files need an upgrade to FIScH 5. You can still view them read-only.')
        actions.append('Migrate to FIScH 5 would update folders and metadata and preserve image pixels and measurements. '
                       'A backup would be kept first. Optional rebuilding could take a long time and change results.')
    else:
        processing = report is not None and (report.outdated_masters or any(
            record.problem and record.step is not None for record in report.records))
        full = full_rebuild_folders(status.states)
        if report is not None and processing:
            summary, action = _processing_messages(report)
            summaries.append(summary)
            if not full or report.analysis_only_rebuild:
                actions.append(action)
        if full and not (report is not None and report.analysis_only_rebuild):
            summaries.append('Some experiments were compacted or migrated without a complete rebuild.')
            actions.append('Rebuild would recreate their full workflow from the original images, including final results. '
                           'Other outdated experiments would rebuild only affected results. Existing versions would be backed up first. '
                           'Rebuilding could take a long time and change results.')
        if locations.needs_update:
            summaries.append('Some saved paths or condition tags no longer match the current folders.')
            actions.append('Update paths and condition tags would refresh saved references and master-table labels. '
                           'Images and individual measurements would stay unchanged.')
        if reviews:
            summaries.append('Some REF/ROI drawings need an alignment check.')
            actions.append('Compare the listed drawings with the current images in the viewer. '
                           'After checking them, the rebuild action would let you confirm their alignment without changing the drawings.')
    if input_warning:
        summaries.append('The channel labels do not match the input images.')
        actions.append('Adjust the channel labels in Convert, or keep the default labels described in Details.')
    if not summaries:
        if status.states:
            summaries.append('Results and saved paths are current.')
            actions.append('No update or rebuild is needed. Compact experiment would free space by removing intermediate files '
                           'while keeping original images, final results and measurements.')
        else:
            summaries.append('No converted experiments were found.')
            actions.append('Converting the original images in the main window would create experiment files.')
    details = '\n\n'.join(text for text in (input_problem, input_warning,
                                           _technical_details(status, report, locations, reviews)) if text)
    return FileGuidance('\n\n'.join(summaries), '\n\n'.join(actions), details)


class FileGuidanceWidget(QWidget):
    """
    Show a summary, useful next actions and an expandable, scrollable file report.
    """

    details_toggled = Signal(bool)

    def __init__(self, guidance: FileGuidance, notice: QLabel, parent: QWidget | None = None) -> None:
        """
        Place explanations beside optional controls and details across both columns.
        """
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(24)
        self._grid.setVerticalSpacing(10)
        self._grid.setColumnStretch(0, 1)
        explanation = QWidget()
        text_layout = QVBoxLayout(explanation)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(10)
        self.summary = self._section(text_layout, 'Summary', guidance.summary, 'file_status_summary')
        self.next_steps = self._section(text_layout, 'What to do next', guidance.next_steps, 'file_next_steps')
        self._grid.addWidget(explanation, 0, 0, Qt.AlignmentFlag.AlignTop)
        self.toggle = QToolButton()
        self.toggle.setText('Details ▾')
        self.toggle.setObjectName('file_details_toggle')
        self.toggle.setCheckable(True)
        self.toggle.setAutoRaise(True)
        self.toggle.setStyleSheet('text-align: left; color: #b8b8b8; font-style: italic;')
        self._grid.addWidget(self.toggle, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        self.details = QPlainTextEdit(guidance.details)
        self.details.setObjectName('file_technical_details')
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(90)
        self.details.setMaximumHeight(220)
        self.details.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.details.hide()
        self.toggle.toggled.connect(self._toggle_details)
        self._grid.addWidget(self.details, 2, 0, 1, 2)
        notice.setObjectName('file_action_notice')
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        notice.hide()
        self._grid.addWidget(notice, 3, 0, 1, 2)

    def add_controls(self, controls: QWidget) -> None:
        """
        Put file actions beside the explanation while keeping the report full-width.
        """
        self._grid.addWidget(controls, 0, 1, Qt.AlignmentFlag.AlignTop)

    def _section(self, layout: QVBoxLayout, title: str, text: str, name: str) -> QLabel:
        """
        Add a labelled plain-text section that wraps at the available width.
        """
        heading = QLabel(title)
        heading.setStyleSheet('font-weight: bold;')
        layout.addWidget(heading)
        label = QLabel(text)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)
        return label

    def _toggle_details(self, expanded: bool) -> None:
        """
        Reveal technical details without forcing long reports to enlarge the dialog.
        """
        self.details.setVisible(expanded)
        self.toggle.setText('Details ▴' if expanded else 'Details ▾')
        self._grid.invalidate()
        self.updateGeometry()
        self.details_toggled.emit(expanded)
