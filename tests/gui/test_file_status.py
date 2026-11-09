"""Coarse file conditions, access suffixes and stable processing status."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PySide6.QtCore import QThread

from fits.environment import constant as cst
from fits.gui.main_window.window import FitsMainWindow
from fits.gui.main_window.run_browser import COMPATIBLE_COLOR, OUTDATED_COLOR
from fits.gui.settings import SettingsAdapter
from fits.gui.theme import get_application
from fits.workflows.checks.locations import LocationIssue, LocationReport
from fits.workflows.checks.models import ArtifactRecord, PreflightReport, RawInputReport, RunCompatibility
from fits.workflows.experiments import ExperimentState


@pytest.fixture
def window() -> Iterator[FitsMainWindow]:
    """
    Start with no selected run and release the window after each status check.
    """
    app = get_application()
    adapter = SettingsAdapter()
    adapter.run_dir = ''
    main = FitsMainWindow(adapter)
    yield main
    main._running = False
    main.close()
    main.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('case,label,color', [
    ('none', 'No run selected', '#ffffff'),
    ('empty', 'Run blocked - editable', '#e57373'),
    ('raw', 'Not processed - editable', '#ffffff'),
    ('bad_raw', 'Run blocked - editable', '#e57373'),
    ('migration', 'Run blocked - read-only', '#e57373'),
    ('results', 'Results outdated - editable', OUTDATED_COLOR),
    ('masters', 'Results outdated - editable', OUTDATED_COLOR),
    ('paths', 'Paths/tags outdated - editable', OUTDATED_COLOR),
    ('mixed', 'Results outdated - editable', OUTDATED_COLOR),
    ('current', 'Up to date - editable', COMPATIBLE_COLOR),
    ('running', 'Running… - read-only', '#ffffff'),
])
def test_file_condition_labels_and_colors(window: FitsMainWindow,
                                          tmp_path: Path,
                                          case: str,
                                          label: str,
                                          color: str,
                                          ) -> None:
    """
    Prioritise blocking and stale results while retaining paths/tag details in the tooltip.
    """
    state = ExperimentState(tmp_path / 'sample_s1')
    states = () if case in ('empty', 'raw', 'bad_raw') else (state,)
    problems = ('An older image needs migration.',) if case == 'migration' else ()
    window._run_status = None if case == 'none' else RunCompatibility(tmp_path, states, (), (), problems)
    raw_problems = ('Cannot read acquisition metadata.',) if case == 'bad_raw' else ()
    counts = {tmp_path / 'sample.nd2': 1} if case in ('raw', 'bad_raw') else {}
    window._raw_input_report = RawInputReport(counts, {}, raw_problems)
    if case in ('results', 'mixed', 'running'):
        record = ArtifactRecord(state.workdir / cst.FITS_MASK_SEG, cst.StepName.SEGMENT,
                                None, 'Input revision differs.')
        window._artifact_report = PreflightReport((record,), (), (), states)
    elif case == 'masters':
        window._artifact_report = PreflightReport((), (), (), states,
                                                  outdated_masters=(tmp_path / cst.MASTER_QUANTI_NAME,))
    if case in ('paths', 'mixed', 'running'):
        window._location_report = LocationReport((LocationIssue(tmp_path / cst.MASTER_QUANTI_NAME,
                                                                 'Condition tags changed.', ()),))
    window._running = case == 'running'
    window._refresh_file_status()
    assert window.file_status_label.text() == label
    assert color in window.file_status_label.styleSheet()
    assert window.file_status_label.toolTip()
    if case == 'mixed':
        assert 'Paths/tags also need updating.' in window.file_status_label.toolTip()


def test_only_valid_raw_inputs_are_not_processed(window: FitsMainWindow, tmp_path: Path) -> None:
    """
    Distinguish a selected empty directory, readable acquisitions and corrupt inputs.
    """
    window.adapter.run_dir = str(tmp_path)
    window._refresh_run_inventory()
    assert window.file_status_label.text() == 'Run blocked - editable'
    source = tmp_path / 'input.tif'
    tifffile.imwrite(source, np.ones((8, 8), dtype=np.uint16), photometric='minisblack')
    window._refresh_run_inventory()
    assert window.file_status_label.text() == 'Not processed - editable'
    source.write_bytes(b'not a TIFF')
    window._refresh_run_inventory()
    assert window.file_status_label.text() == 'Run blocked - editable'
    assert 'input.tif' in window.file_status_label.toolTip()


def test_running_freezes_checks_until_worker_finishes(window: FitsMainWindow,
                                                     tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     ) -> None:
    """
    Keep Running through refresh requests and rescan files after worker cleanup.
    """
    window.adapter.run_dir = str(tmp_path)
    tifffile.imwrite(tmp_path / 'input.tif', np.ones((8, 8), dtype=np.uint16), photometric='minisblack')
    window._refresh_run_inventory()
    assert window.file_status_label.text() == 'Not processed - editable'
    thread = QThread(window)
    window._thread = thread
    window._set_running(True)
    assert window.file_status_label.text() == 'Running… - read-only'
    snapshot = window._run_status

    def unexpected_check(root: Path) -> RunCompatibility:
        """
        Fail if an active worker causes the GUI to inspect changing artifacts.
        """
        pytest.fail('File inventory must remain frozen until the worker finishes.')

    with monkeypatch.context() as context:
        context.setattr('fits.gui.main_window.window.inspect_run_compatibility', unexpected_check)
        window._refresh_run_inventory()
        window._selection_status_changed(tmp_path)
        assert window._run_status is snapshot
        assert window.file_status_label.text() == 'Running… - read-only'
    window._thread_finished()
    assert window._thread is None
    assert window._run_status is not snapshot
    assert window.file_status_label.text() == 'Not processed - editable'


def test_missing_username_does_not_mark_data_blocked(window: FitsMainWindow, tmp_path: Path) -> None:
    """
    Keep launch-configuration validation separate from the condition of valid input files.
    """
    window.adapter.run_dir = str(tmp_path)
    window.adapter.user_name = ''
    tifffile.imwrite(tmp_path / 'input.tif', np.ones((8, 8), dtype=np.uint16), photometric='minisblack')
    window._refresh_run_inventory()
    window._refresh_phase_access()
    assert 'Enter a user name.' in window.adapter.validate_for_run()
    assert window.file_status_label.text() == 'Not processed - editable'
