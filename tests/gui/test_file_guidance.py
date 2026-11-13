"""Check straightforward maintenance guidance and the shared details/action window."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from fisch.environment import constant as cst
from fisch.gui.file_management.guidance import FileGuidanceWidget, file_guidance
from fisch.gui.file_management.manager import manage_files
from fisch.workflows.checks.locations import LocationIssue, LocationReport
from fisch.workflows.checks.models import ArtifactRecord, PreflightReport, RunCompatibility
from fisch.workflows.experiments import ExperimentState


_APP: QApplication | None = None


def _application() -> QApplication:
    """
    Retain the Qt application for dialog and disclosure checks.
    """
    global _APP
    existing = QApplication.instance()
    _APP = existing if isinstance(existing, QApplication) else QApplication([])
    return _APP


def _status(root: Path) -> RunCompatibility:
    """
    Represent a current converted experiment without touching scientific files.
    """
    state = ExperimentState(root / 'control/image/image_s1', completed_steps=('convert',))
    return RunCompatibility(root, (state,), (), (state.workdir / cst.ARRAY_RAW,), ())


def test_master_guidance_explains_reuse_and_lists_affected_tables(tmp_path: Path) -> None:
    """
    Describe changed analysis membership without suggesting a new image-processing run.
    """
    master = tmp_path / cst.MASTER_QUANTI_NAME
    report = PreflightReport((), (), (), (), outdated_masters=(master,))
    guidance = file_guidance(_status(tmp_path), report, LocationReport())
    assert 'master tables are out of date' in guidance.summary
    assert 'experiments' in guidance.summary
    assert 'Rebuild analysis would combine' in guidance.next_steps
    assert 'would reuse existing images and individual measurements' in guidance.next_steps
    assert str(master) in guidance.details
    assert 'recalculates' not in guidance.next_steps


@pytest.mark.parametrize('case', ['current', 'fresh', 'migration', 'processing', 'locations', 'compacted', 'drawings', 'inputs'])
def test_common_guidance_retains_the_reason_and_next_action(tmp_path: Path, case: str) -> None:
    """
    Explain common states with actionable sentences and affected-file details.
    """
    status = _status(tmp_path)
    report: PreflightReport | None = None
    locations = LocationReport()
    reviews: tuple[tuple[Path, Path], ...] = ()
    input_problem = ''
    expected = ('current', 'No update or rebuild is needed', '')
    if case == 'fresh':
        status = replace(status, states=(), files=())
        expected = ('No converted experiments', 'Converting the original images', '')
    elif case == 'migration':
        status = replace(status, problems=('Older artifact: old/proc_array.tif',))
        expected = ('read-only', 'preserve image pixels and measurements', 'old/proc_array.tif')
    elif case == 'processing':
        record = ArtifactRecord(status.states[0].workdir / cst.ARRAY_BGSUB, cst.StepName.BG_SUB,
                                None, 'Input revision differs: proc_array_raw.tif')
        report = PreflightReport((record,), (), (), status.states)
        expected = ('older inputs', 'would recalculate the affected files', str(record.path))
    elif case == 'locations':
        path = tmp_path / cst.MASTER_QUANTI_NAME
        locations = LocationReport((LocationIssue(path, 'Saved condition: control; current folder: treated', ()),))
        expected = ('condition tags', 'Images and individual measurements would stay unchanged', str(path))
    elif case == 'compacted':
        status = replace(status, states=(replace(status.states[0], compacted=True),))
        expected = ('compacted', 'including final results', str(status.states[0].workdir))
    elif case == 'drawings':
        reviews = ((status.states[0].workdir / 'proc_roi_area.tif', status.files[0]),)
        expected = ('alignment check', 'Compare the listed drawings', str(reviews[0][0]))
    elif case == 'inputs':
        input_problem = 'sample.nd2: inconsistent channel counts'
        expected = ('input files need attention', 'Check the input files and channel settings', input_problem)
    guidance = file_guidance(status, report, locations, reviews, input_problem=input_problem)
    assert expected[0] in guidance.summary
    assert expected[1] in guidance.next_steps
    assert expected[2] in guidance.details


def test_guidance_preserves_multiple_simultaneous_issues(tmp_path: Path) -> None:
    """
    Keep location, processing and channel warnings visible together.
    """
    status = _status(tmp_path)
    record = ArtifactRecord(status.files[0], cst.StepName.CONVERT, None, 'Processing settings differ')
    locations = LocationReport((LocationIssue(tmp_path / 'state.json', 'Old artifact path', ()),))
    guidance = file_guidance(status, PreflightReport((record,), (), (), status.states), locations,
                             input_warning='Expected 3 channels, got 2 channel labels')
    assert 'older inputs' in guidance.summary and 'condition tags' in guidance.summary
    assert 'channel labels' in guidance.summary
    assert 'Old artifact path' in guidance.details
    assert record.problem in guidance.details
    assert 'Expected 3 channels' in guidance.details


def test_details_disclosure_keeps_long_reports_scrollable(tmp_path: Path) -> None:
    """
    Expand and collapse a bounded report area instead of enlarging it for every file.
    """
    app = _application()
    guidance = file_guidance(_status(tmp_path), None, LocationReport())
    guidance = replace(guidance, details='\n'.join(f'file_{index}.tif' for index in range(1000)))
    panel = FileGuidanceWidget(guidance, QLabel())
    panel.resize(500, 500)
    panel.show()
    app.processEvents()
    try:
        assert panel.details.isHidden()
        panel.toggle.click()
        app.processEvents()
        assert panel.details.isVisible() and panel.details.isReadOnly()
        assert panel.details.height() <= 220
        assert panel.details.verticalScrollBar().maximum() > 0
        panel.toggle.click()
        assert panel.details.isHidden()
    finally:
        panel.close()


def test_manager_combines_master_status_and_relevant_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Show master-only guidance beside the enabled analysis rebuild control.
    """
    app = _application()
    status = _status(tmp_path)
    master = tmp_path / cst.MASTER_QUANTI_NAME
    report = PreflightReport((), (), (), status.states, outdated_masters=(master,))
    monkeypatch.setattr('fisch.gui.file_management.manager.inspect_run_compatibility', lambda root: status)
    monkeypatch.setattr('fisch.gui.file_management.manager.inspect_run', lambda *args, **kwargs: report)
    monkeypatch.setattr('fisch.gui.file_management.manager.inspect_locations', lambda *args: LocationReport())
    monkeypatch.setattr('fisch.gui.file_management.manager.snapshots', lambda *args: ())
    monkeypatch.setattr('fisch.gui.file_management.manager.geometry_reviews', lambda *args: ())
    monkeypatch.setattr('fisch.gui.file_management.manager.api.can_compact', lambda *args: False)

    def inspect() -> None:
        """
        Read all three guidance sections and check the matching action states.
        """
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        try:
            guidance = dialog.findChild(FileGuidanceWidget)
            assert guidance is not None
            assert 'master tables are out of date' in guidance.summary.text()
            assert 'would reuse existing images' in guidance.next_steps.text()
            assert str(master) in guidance.details.toPlainText()
            buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
            assert buttons['Rebuild analysis…'].isEnabled()
            assert not buttons['Update paths and condition tags…'].isEnabled()
            assert len([name for name in buttons if name.startswith('Rebuild')]) == 1
            QTest.qWait(20)
            collapsed = dialog.size()
            for _ in range(2):
                guidance.toggle.click()
                QTest.qWait(20)
                assert dialog.height() >= collapsed.height()
                assert guidance.details.width() > guidance.summary.width()
                right = guidance.details.mapTo(dialog, guidance.details.rect().topRight()).x()
                button = buttons['Rebuild analysis…']
                assert right >= button.mapTo(dialog, button.rect().topRight()).x()
                compact = buttons['Compact experiment…']
                assert guidance.details.mapTo(dialog, guidance.details.rect().topLeft()).y() > compact.mapTo(
                    dialog, compact.rect().bottomLeft()).y()
                guidance.toggle.click()
                QTest.qWait(20)
                assert dialog.size() == collapsed
                assert guidance.details.isHidden()
        finally:
            dialog.reject()

    QTimer.singleShot(0, inspect)
    assert not manage_files(tmp_path)
