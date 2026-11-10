"""Browser multi-selection, inclusion actions and propagated exclusion badges."""

import os
from dataclasses import replace
from pathlib import Path
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QApplication

from fits.gui.main_window.run_browser import OUTDATED_COLOR, RunDirectoryBrowser
from fits.workflows.checks.models import RunCompatibility
from fits.workflows.experiments import ExperimentState


def _application() -> QApplication:
    """
    Reuse the process's Qt application for offscreen browser checks.
    """
    existing = QApplication.instance()
    assert existing is None or isinstance(existing, QApplication)
    return existing or QApplication([])


def _state(root: Path, name: str, excluded: bool) -> ExperimentState:
    """
    Represent a converted series beneath a portable acquisition folder.
    """
    folder = root / 'condition' / 'acquisition' / name
    folder.mkdir(parents=True)
    return ExperimentState(workdir=folder, completed_steps=('convert',), excluded=excluded)


def test_browser_mixed_selection_actions_and_parent_badges(tmp_path: Path) -> None:
    """
    Show partial and complete exclusion without preventing folder inspection.
    """
    app = _application()
    active = _state(tmp_path, 'input_s1', False)
    excluded = _state(tmp_path, 'input_s2', True)
    browser = RunDirectoryBrowser()
    browser.set_root(tmp_path)
    status = RunCompatibility(tmp_path, (active, excluded), (), (), ())
    browser.set_experiment_status(status)
    app.processEvents()
    assert not browser.exclusion_button.isEnabled()
    for folder in (tmp_path, active.workdir.parent.parent, active.workdir.parent):
        assert browser.model.folder_exclusion[folder] == (1, 2)
        index = browser.model.index(str(folder))
        assert browser.model.data(index, Qt.ItemDataRole.ToolTipRole) == '1 of 2 experiments excluded'
        assert isinstance(browser.model.data(index, Qt.ItemDataRole.DecorationRole), QIcon)
    index = browser.model.index(str(excluded.workdir))
    browser.tree.selectionModel().select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                                         | QItemSelectionModel.SelectionFlag.Rows)
    assert browser.exclusion_button.isEnabled()
    assert browser.exclusion_button.text() == 'Re-include experiments'
    assert browser.model.data(index, Qt.ItemDataRole.ForegroundRole) == QColor('#999999')
    assert browser.model.flags(index) & Qt.ItemFlag.ItemIsEnabled
    assert browser.model.flags(index) & Qt.ItemFlag.ItemIsSelectable
    requests: list[tuple[list[Path], bool]] = []

    def capture(folders: list[Path], value: bool) -> None:
        """
        Record the requested whole-selection action.
        """
        requests.append((folders, value))

    browser.exclusion_requested.connect(capture)
    browser.exclusion_button.click()
    assert requests == [([excluded.workdir], False)]
    # Selecting the parent and an already selected child covers each series once.
    parent_index = browser.model.index(str(active.workdir.parent))
    browser.tree.selectionModel().select(parent_index, QItemSelectionModel.SelectionFlag.Select
                                         | QItemSelectionModel.SelectionFlag.Rows)
    assert browser.exclusion_button.text() == 'Exclude experiments'
    browser.exclusion_button.click()
    assert requests[-1][1] is True
    browser.set_processing(True)
    assert not browser.exclusion_button.isEnabled()
    browser.set_processing(False)
    assert browser.exclusion_button.isEnabled()
    browser.set_experiment_status(replace(status, states=(replace(active, excluded=True), excluded)))
    assert browser.exclusion_button.text() == 'Re-include experiments'
    assert browser.model.folder_exclusion[active.workdir.parent] == (2, 2)
    browser.tree.clearSelection()
    assert not browser.exclusion_button.isEnabled()
    browser.close()


def test_files_and_migrated_checkpoints_do_not_enable_exclusion(tmp_path: Path) -> None:
    """
    Require a converted-folder selection and a fully rebuilt migrated experiment.
    """
    app = _application()
    state = replace(_state(tmp_path, 'input_s1', False), migration_checkpoint='bg_sub')
    image = state.workdir / 'fits_array.tif'
    image.touch()
    browser = RunDirectoryBrowser()
    browser.set_root(tmp_path)
    browser.set_experiment_status(RunCompatibility(tmp_path, (state,), (), (), ()))
    app.processEvents()
    browser.select_path(image)
    assert not browser.exclusion_button.isEnabled()
    browser.select_path(state.workdir)
    assert not browser.exclusion_button.isEnabled()
    browser.set_experiment_status(RunCompatibility(tmp_path, (replace(state, migration_checkpoint=None),), (), (), ()))
    assert browser.exclusion_button.isEnabled()
    browser.close()


def test_main_browser_toggle_and_analysis_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Persist browser toggles, report stale masters, and rebuild without touching individual results.
    """
    import numpy as np
    import pandas as pd
    import tifffile
    from scope_io import ScopeIO
    from PySide6.QtWidgets import QLabel
    from fits.environment import constant as cst
    from fits.gui.file_management.manager import _rebuild_action
    from fits.gui.main_window.window import FitsMainWindow
    from fits.gui.settings import SettingsAdapter
    from fits.settings.models import ConvertSettings
    from fits.tasks.analysis.aggregate import save_master_analysis_table
    from fits.tasks.common.table_results import save_parquet
    from fits.tasks.convert import convert
    from fits.workflows.artifacts.provenance import read_metadata
    from fits.workflows.definitions.registry import REGISTRY
    from fits.workflows.experiments import load_experiment_state, save_experiment_state
    from fits.workflows.file_management.rebuild import ProcessingPlan

    app = _application()
    monkeypatch.setattr('fits.gui.file_management.manager.run_file_task', lambda task, *args, **kwargs: task())
    source = tmp_path / 'input.tif'
    tifffile.imwrite(source, np.ones((8, 8), dtype=np.uint16), metadata={'axes': 'YX'})
    state = convert(ConvertSettings(), ExperimentState.init(tmp_path, source, run_dir=tmp_path),
                    REGISTRY[cst.StepName.CONVERT].profile)[0]
    raw = state.artifact(cst.ARTI_IMG_RAW)
    assert raw is not None
    payload = read_metadata(raw)
    table = save_parquet(pd.DataFrame({'distance': [1]}), state.workdir / cst.FITS_DISTANCE_PROFILE_NAME,
                         payload.with_artifact(artifact_type=cst.ARTI_DIST_PROF).new_revision([
                             {'artifact_path': raw.name, 'created_at': payload.artifact.created_at}]))
    state = state.with_complete_step(step_name=cst.StepName.DISTANCE_PROFILE,
                                     artifact_kind=cst.ARTI_DIST_PROF, artifact_path=table)
    save_experiment_state(state)
    master = save_master_analysis_table([state], tmp_path, artifact_kind=cst.ARTI_DIST_PROF,
                                        output_name=cst.MASTER_DISTANCE_PROFILE_NAME)
    assert master is not None
    original_table = table.read_bytes()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_step_enabled(cst.StepName.CONVERT, False)
    adapter.save_to_run_dir()
    window = FitsMainWindow(adapter)
    window.show()
    app.processEvents()

    def unexpected_processing(plan: ProcessingPlan) -> None:
        """
        Fail if valid individual measurements are unnecessarily rerun.
        """
        raise AssertionError('Only master tables need rebuilding.')

    try:
        assert window.run_browser.select_path(state.workdir)
        window.run_browser.exclusion_button.click()
        assert load_experiment_state(state.workdir).excluded
        assert window._artifact_report is not None
        assert window._artifact_report.outdated_masters == (master,)
        master_index = window.run_browser.model.index(str(master))
        assert window.run_browser.model.data(master_index, Qt.ItemDataRole.ForegroundRole) == QColor(OUTDATED_COLOR)
        assert window.file_status_label.text() == 'Results outdated - editable'
        assert not window._artifact_report.blocking_conflicts, window._artifact_report.describe()
        assert not window._location_report.needs_update
        action = _rebuild_action(tmp_path, window, QLabel(), unexpected_processing)
        assert action is not None
        action()
        assert not master.exists()
        window._refresh_run_inventory()
        assert window.run_browser.exclusion_button.text() == 'Re-include experiments'
        window.run_browser.exclusion_button.click()
        assert not load_experiment_state(state.workdir).excluded
        assert window._artifact_report is not None and window._artifact_report.outdated_masters == (master,)
        assert not window._artifact_report.blocking_conflicts, window._artifact_report.describe()
        action = _rebuild_action(tmp_path, window, QLabel(), unexpected_processing)
        assert action is not None
        action()
        assert pd.read_parquet(master)['distance'].tolist() == [1]
        assert table.read_bytes() == original_table
        window._refresh_run_inventory()
        assert window.run_browser.model.data(window.run_browser.model.index(str(master)),
                                             Qt.ItemDataRole.ForegroundRole) != QColor(OUTDATED_COLOR)
        # A real upstream revision invalidates both the saved analysis and its master.
        from scope_io.writers.metadata_update import rewrite_metadata
        previous = read_metadata(raw)
        inputs = previous.artifact.derived_from
        assert isinstance(inputs, list)
        rewrite_metadata(raw, previous.new_revision(inputs))
        window._refresh_run_inventory()
        for path in (table, master):
            index = window.run_browser.model.index(str(path))
            assert window.run_browser.model.data(index, Qt.ItemDataRole.ForegroundRole) == QColor(OUTDATED_COLOR)
        current = read_metadata(raw)
        save_parquet(pd.DataFrame({'distance': [1]}), table,
                     current.with_artifact(artifact_type=cst.ARTI_DIST_PROF).new_revision([
                         {'artifact_path': raw.name, 'created_at': current.artifact.created_at}]))
        save_master_analysis_table([state], tmp_path, artifact_kind=cst.ARTI_DIST_PROF,
                                    output_name=cst.MASTER_DISTANCE_PROFILE_NAME)
        window._refresh_run_inventory()
        for path in (table, master):
            index = window.run_browser.model.index(str(path))
            assert window.run_browser.model.data(index, Qt.ItemDataRole.ForegroundRole) != QColor(OUTDATED_COLOR)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
