"""Compact preview and responsive publication shared by GUI and CLI."""

from __future__ import annotations

from collections.abc import Callable
from PySide6.QtWidgets import QWidget, QDialog, QDialogButtonBox, QLabel, QVBoxLayout
from fisch.workflows.file_management.compaction import CompactionPlan
from fisch.workflows.checks.models import PreflightReport
from pathlib import Path
from fisch.workflows.file_management.api import compact_run, apply_compaction
from fisch.gui.artifact_decisions import choose_artifacts
from fisch.gui.file_management.tasks import run_file_task
from fisch.gui.file_preview.widget import FilePreviewWidget
from fisch.gui.file_preview.compaction import compaction_groups
from fisch.gui.file_preview.review import review_tabs, size_file_review


def confirm_compaction(plan: CompactionPlan, parent: QWidget | None = None) -> bool:
    """
    Show the exact retained and removed files before compaction publication.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Preview experiment compaction")
    layout = QVBoxLayout(dialog)
    label = QLabel("Review the retained outputs and files to remove. Original acquisitions and REF/ROI masks are preserved. Intermediate files are removed without creating a backup.")
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addWidget(review_tabs(FilePreviewWidget(compaction_groups(plan)), plan.describe()))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    accept = buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert accept is not None
    accept.setText("Compact listed files")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    size_file_review(dialog)
    return dialog.exec() == QDialog.DialogCode.Accepted


def publish_compaction(plan: CompactionPlan, parent: QWidget | None = None) -> tuple[Path, ...]:
    """
    Publish verified canonical outputs using the shared responsive file worker.
    """
    return run_file_task(lambda: apply_compaction(plan),
                         parent,
                         title='Compacting experiments',
                         message='Publishing retained files and verifying metadata before cleanup…',
                         )


def run_compaction_ui(root: str | Path,
                      parent: QWidget | None = None,
                      rebuild: Callable[[PreflightReport], None] | None = None,
                      ) -> tuple[Path, ...]:
    """
    Review conflicts, preview cleanup and compact experiments through shared dialogs.
    """
    return compact_run(root,
                       choose=lambda report: choose_artifacts(report, parent, compact=True),
                       confirm=lambda plan: confirm_compaction(plan, parent),
                       rebuild=rebuild,
                       publisher=lambda plan: publish_compaction(plan, parent),
                       )
