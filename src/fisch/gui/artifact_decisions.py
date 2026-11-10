"""Shared GUI/CLI artifact decisions, always displayed on the Qt main thread."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QTabWidget, QVBoxLayout
from fisch.workflows.checks.models import PreflightReport
from fisch.gui.file_preview.review import size_file_review
from fisch.gui.artifact_lineage import ArtifactLineageWidget


def choose_artifacts(report: PreflightReport, parent: QWidget | None = None, *, compact: bool = False) -> str:
    """
    Choose artifacts.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Earlier-version results" if report.legacy else "Review artifact conflicts")
    layout = QVBoxLayout(dialog)
    if report.legacy:
        text = ("Earlier-version results are read-only and incompatible with this workflow. "
                "Rebuilding requires the original acquisitions, may take substantial time, "
                "and may change results because FIScH or its processing dependencies have changed. "
                "Old results are preserved. Hand-drawn masks may require review or recreation.")
    elif compact:
        text = "Review the conflicts before compacting. You may deliberately retain the existing downstream results."
    else:
        text = "Review exactly which results will be rebuilt or retained. Existing conflicts remain detectable if retained."
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    details = QPlainTextEdit(report.describe())
    details.setReadOnly(True)
    tabs = QTabWidget()
    tabs.addTab(ArtifactLineageWidget(report, compact=compact), "Run overview")
    tabs.addTab(details, "Full details")
    layout.addWidget(tabs, 1)
    buttons = QDialogButtonBox()
    decision = ["cancel"]

    def select(value: str) -> None:
        """
        Return the current select.
        """
        decision[0] = value
        dialog.accept()

    choices = [("Rebuild results…", "rebuild")] if report.legacy else (
        [("Rebuild downstream, then compact", "rebuild"),
         ("Keep existing downstream results and compact", "continue")] if compact else
        [("Selected step and downstream" if report.overwritten else "Rebuild affected results", "rebuild"),
         ("Selected step only" if report.overwritten else "Continue without rebuilding",
          "selected" if report.overwritten else "continue")])
    for title, value in choices:
        button = buttons.addButton(title, QDialogButtonBox.ButtonRole.ActionRole)
        button.clicked.connect(lambda checked=False, choice=value: select(choice))
    cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
    cancel.clicked.connect(dialog.reject)
    layout.addWidget(buttons)
    size_file_review(dialog)
    dialog.exec()
    return decision[0]
