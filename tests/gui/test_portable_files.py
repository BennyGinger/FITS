import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import numpy as np
import pytest
import tifffile
from PySide6.QtWidgets import QApplication
from fits_io import FitsIO
from fits.environment import constant as cst
from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.workflows.experiments import ExperimentState, save_experiment_state, discover_saved_states

_APP = None


@pytest.fixture
def current_window(tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    group = tmp_path / 'control/image'
    group.mkdir(parents=True)
    source = group / 'image.tif'
    tifffile.imwrite(source, np.ones((8, 8), dtype=np.uint16), photometric='minisblack')
    series = group / 'image_s1'
    series.mkdir()
    reader = FitsIO.from_path(source)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_RAW,
        channel_labels=['Red'], custom_metadata={'pipeline_meta': {'version': '4.0.0'}}).new_revision()
    image = reader.save_array(np.ones((8, 8), dtype=np.uint16), metadata=payload, output_path=series / cst.FITS_ARRAY_RAW)
    save_experiment_state(ExperimentState.init(series, source, run_dir=tmp_path).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=image))
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_field_value(cst.StepName.CONVERT, 'channel_labels', ['Red'])
    adapter.save_to_run_dir()
    window = FitsMainWindow(adapter)
    window.show()
    _APP.processEvents()
    yield window, series
    window.close()
    window.deleteLater()
    _APP.processEvents()


def test_summary_and_mixed_run_block_all_processing(current_window, tmp_path):
    window, series = current_window
    assert 'Current' in window.file_status_label.text()
    assert 'Red' in window.file_channels_label.text()
    assert window.file_size_label.text().startswith('Run size:')
    assert 'incompatible' not in window._file_details_text()
    old = tmp_path / 'old'
    old.mkdir()
    tifffile.imwrite(old / cst.FITS_ARRAY_NAME, np.ones((8, 8), dtype=np.uint16))
    window._refresh_run_inventory()
    window._refresh_phase_access()
    assert window.file_status_label.text() == 'Upgrade to FITS v4 required - read-only'
    assert 'read-only' in window.file_status_label.text()
    details = window._file_details_text()
    assert 'incompatible' in details and 'Manage files' in details
    assert 'preserves image pixels' in details and 'results may change' in details
    assert not window.run_button.isEnabled()
    assert not hasattr(window, 'compact_button')
    assert not window.channel_labels_button.isEnabled()
    assert window.manage_files_button.isEnabled()
    assert window.tracking_viewer_button.isEnabled()


def test_folder_status_and_details_popup(current_window, tmp_path):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QDialog, QPlainTextEdit
    from fits.gui.main_window.run_browser import COMPATIBLE_COLOR, OUTDATED_COLOR
    window, series = current_window
    model = window.run_browser.model
    index = model.index(str(series))
    assert model.data(index, Qt.ItemDataRole.ForegroundRole).name() == COMPATIBLE_COLOR
    old = tmp_path / 'old'
    old.mkdir()
    tifffile.imwrite(old / cst.FITS_ARRAY_NAME, np.ones((8, 8), dtype=np.uint16))
    window._refresh_run_inventory()
    _APP.processEvents()
    old_index = model.index(str(old))
    assert model.data(old_index, Qt.ItemDataRole.ForegroundRole).name() == OUTDATED_COLOR
    assert not model.data(old_index, Qt.ItemDataRole.DecorationRole).isNull()
    assert model.data(index, Qt.ItemDataRole.ForegroundRole).name() == COMPATIBLE_COLOR
    assert OUTDATED_COLOR in window.file_status_label.styleSheet()
    def inspect_popup():
        dialog = _APP.activeModalWidget()
        assert isinstance(dialog, QDialog)
        assert 'read-only' in dialog.findChild(QPlainTextEdit).toPlainText()
        dialog.reject()
    QTimer.singleShot(0, inspect_popup)
    window.file_details_button.click()
    assert window.run_browser.select_path(series)
    assert window.file_size_label.text().startswith('Run size:')
    assert 'Red' in window.file_channels_label.text()


def test_runtime_retains_space_only_and_promotes_series_to_run(current_window, tmp_path):
    window, series = current_window
    runtime = window.runtime_editor._advanced_group
    collapsed = runtime.sizeHint().height()
    runtime.setChecked(True)
    _APP.processEvents()
    assert runtime.sizeHint().height() == collapsed
    assert not window._editors[cst.StepName.CONVERT]._advanced_group.content.sizePolicy().retainSizeWhenHidden()
    window._switch_run_dir(str(series))
    _APP.processEvents()
    assert Path(window.adapter.run_dir) == tmp_path
    assert window.run_browser.selected_path == series


def test_manage_refresh_runs_after_review_and_cancel_preserves_files(current_window, tmp_path, monkeypatch):
    import shutil
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QPushButton
    from fits.gui.file_management.manager import manage_files
    from fits.workflows.artifacts.provenance import read_metadata
    window, series = current_window
    source = series / cst.FITS_ARRAY_RAW
    stamp = read_metadata(source).fits_io.created_at
    before = source.read_bytes()
    # Selecting one series must still review/update the other series in the run.
    other = series.parent / 'image_s2'
    other.mkdir()
    other_image = other / cst.FITS_ARRAY_RAW
    shutil.copy2(source, other_image)
    save_experiment_state(ExperimentState.init(other, series.parent / 'image.tif', run_dir=tmp_path).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=other_image))
    import json
    state_path = next((series.parent / '.fits_experiment/experiment_state').glob('*/experiment_state.json'))
    payload = json.loads(state_path.read_text())
    payload['artifacts'][cst.ARTI_RAW] = str(series.parent / 'image.tif')
    state_path.write_text(json.dumps(payload))
    previews = []
    def confirm(*args, **kwargs):
        previews.append(args[1])
        return len(previews) > 1
    def choose():
        dialog = _APP.activeModalWidget()
        assert isinstance(dialog, QDialog)
        next(button for button in dialog.findChildren(QPushButton)
             if button.text() == 'Update paths and condition tags…').click()
        if dialog.isVisible():
            dialog.reject()
    monkeypatch.setattr('fits.gui.file_management.manager.confirm_files', confirm)
    QTimer.singleShot(0, choose)
    assert not manage_files(tmp_path, series, window)
    assert source.read_bytes() == before
    QTimer.singleShot(0, choose)
    assert manage_files(tmp_path, series, window)
    assert source.read_bytes() == before
    assert read_metadata(source).fits_io.created_at == stamp
    assert len(previews) == 2 and all('Saved artifact paths' in text for text in previews)
    assert other_image.read_bytes() == before


def test_manage_actions_disable_unavailable_work(current_window: tuple[FitsMainWindow, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep useful actions enabled and place guidance to their left.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QLabel, QPushButton
    from fits.gui.file_management.manager import manage_files
    window, series = current_window
    previews = []
    monkeypatch.setattr('fits.gui.file_management.manager.confirm_files', lambda *args, **kwargs: previews.append(args[1]) or False)
    def inspect() -> None:
        """
        Check current-run action states and the two-column file layout.
        """
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        try:
            buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
            assert not buttons['Rebuild results…'].isEnabled()
            assert not buttons['Update paths and condition tags…'].isEnabled()
            assert buttons['Compact experiment…'].isEnabled()
            for title in ('Restore selected backup…', 'Delete selected backups…'):
                assert not buttons[title].isEnabled()
            assert 'Migrate to FITS 4…' not in buttons
            notice = dialog.findChild(QLabel, 'file_action_notice')
            assert notice is not None
            rebuild = buttons['Rebuild results…']
            assert notice.mapTo(dialog, notice.rect().topRight()).x() < rebuild.mapTo(dialog, rebuild.rect().topLeft()).x()
            rebuild.click()
            assert not previews
            assert 'current' in rebuild.toolTip()
            from PySide6.QtWidgets import QGroupBox
            panel = next(group for group in dialog.findChildren(QGroupBox) if group.title() == 'Experiment files')
            assert len(panel.findChildren(QPushButton)) == 3
        finally:
            dialog.reject()
    QTimer.singleShot(0, inspect)
    assert not manage_files(tmp_path, series, window)


def test_loading_stale_results_warns_without_locking_current_format(current_window, tmp_path):
    from PySide6.QtCore import Qt
    from fits.workflows.artifacts.provenance import read_metadata
    from fits_io.writers.metadata_update import rewrite_metadata
    from fits.workflows.experiments import discover_saved_states
    from fits.gui.main_window.run_browser import OUTDATED_COLOR
    window, series = current_window
    state = discover_saved_states(tmp_path)[0]
    raw = state.artifact(cst.ARTI_IMG_RAW)
    reader = FitsIO.from_path(raw)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_BGSUB).new_revision([
        {'artifact_path': raw.name, 'created_at': read_metadata(raw).fits_io.created_at}])
    bg = reader.save_array(reader.get_array().array, metadata=payload, output_path=series / cst.FITS_ARRAY_BGSUB)
    save_experiment_state(state.with_complete_step(step_name=cst.StepName.BG_SUB, artifact_kind=cst.ARTI_IMG_BGSUB, artifact_path=bg))
    rewrite_metadata(raw, read_metadata(raw).new_revision())
    window._refresh_run_inventory()
    assert not window._run_status.outdated
    assert window._artifact_report.conflicts
    assert window.file_status_label.text() == 'Outdated downstream results'
    assert 'Input revision differs' in window._file_details_text()
    assert OUTDATED_COLOR in window.file_status_label.styleSheet()
    model = window.run_browser.model
    assert model.data(model.index(str(series)), Qt.ItemDataRole.ForegroundRole).name() == OUTDATED_COLOR
    assert _APP.activeModalWidget() is None


@pytest.mark.parametrize('rebuild', [False, True])
def test_migration_dialog_defaults_to_metadata_only(tmp_path, rebuild):
    from fits.workflows.file_management.relocation import PortablePlan
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QCheckBox, QDialog
    from fits.gui.file_management.manager import confirm_migration
    global _APP
    _APP = QApplication.instance() or QApplication([])
    def inspect():
        dialog = _APP.activeModalWidget()
        checkbox = dialog.findChild(QCheckBox)
        assert not checkbox.isChecked()
        checkbox.setChecked(rebuild)
        dialog.accept()
    QTimer.singleShot(0, inspect)
    assert confirm_migration(PortablePlan(tmp_path, (), (), ())) is rebuild


def test_manager_migrates_real_legacy_run_without_launching_processing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPushButton
    from test_file_management import legacy_run
    from fits.gui.file_management.manager import manage_files
    from fits.workflows.checks.compatibility import inspect_run_compatibility
    global _APP
    _APP = QApplication.instance() or QApplication([])
    adapter, old, pixels = legacy_run(tmp_path)
    calls = []
    monkeypatch.setattr('fits.gui.file_management.manager.confirm_migration', lambda *args: False)
    def choose():
        dialog = _APP.activeModalWidget()
        assert isinstance(dialog, QDialog)
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        for title in ('Update paths and condition tags…', 'Compact experiment…'):
            assert not buttons[title].isEnabled()
        assert buttons['Migrate to FITS 4…'].isEnabled()
        buttons['Migrate to FITS 4…'].click()
    QTimer.singleShot(0, choose)
    assert manage_files(tmp_path, old.workdir, run_processing=lambda plan: calls.append(plan))
    assert not calls
    status = inspect_run_compatibility(tmp_path)
    assert not status.outdated

    def inspect_history() -> None:
        """
        Show the whole-run backup even when a single migrated series is selected.
        """
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        try:
            history = dialog.findChild(QListWidget)
            assert history is not None and history.count() == 1
            assert history.item(0).text().startswith('Whole run /')
            labels = dialog.findChildren(QLabel)
            assert any('Select one backup to restore' in label.text() for label in labels)
            assert any('No backup selected.' in label.text() for label in labels)
            buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
            assert not buttons['Restore selected backup…'].isEnabled()
            assert not buttons['Delete selected backups…'].isEnabled()
            history.setCurrentRow(0)
            assert buttons['Restore selected backup…'].isEnabled()
            assert buttons['Delete selected backups…'].isEnabled()
            assert any('1 backup selected.' == label.text() for label in labels)
            history.clearSelection()
            assert not buttons['Restore selected backup…'].isEnabled()
            assert not buttons['Delete selected backups…'].isEnabled()
        finally:
            dialog.reject()

    QTimer.singleShot(0, inspect_history)
    assert not manage_files(tmp_path, status.states[0].workdir)


def test_manage_files_preserves_legacy_settings_before_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep original settings intact until they have been copied into migration history.
    """
    from test_file_management import legacy_run
    global _APP
    _APP = QApplication.instance() or QApplication([])
    adapter, _, _ = legacy_run(tmp_path)
    settings = tmp_path / '.fits/fits_settings.toml'
    before = settings.read_bytes()
    window = FitsMainWindow(adapter)
    calls: list[Path] = []

    def reject_settings_write() -> None:
        """
        Reject any attempt to rewrite old settings before opening file management.
        """
        pytest.fail('Old settings must not be overwritten before migration retention.')

    def inspect_manager(root: Path, *args: object, **kwargs: object) -> bool:
        """
        Verify the manager receives the unchanged legacy settings.
        """
        calls.append(root)
        assert settings.read_bytes() == before
        return False

    monkeypatch.setattr(window, '_save_settings', reject_settings_write)
    monkeypatch.setattr('fits.gui.main_window.window.manage_files', inspect_manager)
    try:
        window._manage_files()
        assert calls == [tmp_path] and settings.read_bytes() == before
    finally:
        window.close()


def test_optional_migration_rebuild_runs_the_complete_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep migration optional but route its checked rebuild choice through a full backed-up run.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QPushButton
    from test_file_management import legacy_run, mock_rebuild_processing
    from fits.gui.file_management.manager import manage_files
    from fits.workflows.file_management.rebuild import ProcessingPlan
    from fits.workflows.file_management.history import snapshots
    from fits.workflows.checks.artifacts import inspect_run
    from fits.settings.loader import load_settings, run_settings_path
    from fits.pipeline import start_pipeline
    global _APP
    _APP = QApplication.instance() or QApplication([])
    adapter, _, pixels = legacy_run(tmp_path)
    mock_rebuild_processing(monkeypatch, adapter)
    adapter.save_to_run_dir()
    processing: list[ProcessingPlan] = []
    monkeypatch.setattr('fits.gui.file_management.manager.confirm_migration', lambda *args: True)

    def confirm(*args: object, **kwargs: object) -> bool:
        """
        Reject a duplicate rebuild review after migration was already accepted.
        """
        pytest.fail('The migration rebuild option must not open a second review dialog.')

    def run(plan: ProcessingPlan) -> None:
        """
        Run the reviewed scope through the same pipeline entry point as GUI/CLI workers.
        """
        processing.append(plan)
        start_pipeline(adapter.save_to_run_dir(), maintenance=plan, terminal_progress=False)

    def choose() -> None:
        """
        Accept the manager's migration action on its Qt thread.
        """
        dialog = _APP.activeModalWidget()
        assert isinstance(dialog, QDialog)
        next(button for button in dialog.findChildren(QPushButton) if button.text() == 'Migrate to FITS 4…').click()

    monkeypatch.setattr('fits.gui.file_management.manager.confirm_files', confirm)
    QTimer.singleShot(0, choose)
    assert manage_files(tmp_path, run_processing=run)
    state = discover_saved_states(tmp_path)[0]
    assert len(processing) == 1
    assert processing[0].action == 'rebuild' and processing[0].scope[state.workdir] == ('convert', 'bg_sub')
    assert state.migration_checkpoint is None
    np.testing.assert_array_equal(FitsIO.from_path(state.artifact(cst.ARTI_IMG)).get_array().array, pixels + 1)
    assert not inspect_run(tmp_path, load_settings(run_settings_path(tmp_path)), for_execution=False).conflicts
    assert len(snapshots(tmp_path)) == 2


def test_empty_run_disables_file_actions(current_window: tuple[FitsMainWindow, Path], tmp_path: Path) -> None:
    """
    Keep every data action unavailable until an experiment has been converted.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QLabel, QPushButton
    from fits.gui.file_management.manager import manage_files

    empty = tmp_path / 'empty'
    empty.mkdir()

    def inspect() -> None:
        """
        Check the explanatory panel and leave Close usable.
        """
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        try:
            buttons = dialog.findChildren(QPushButton)
            assert all(not button.isEnabled() for button in buttons if button.text() != 'Close')
            notice = dialog.findChild(QLabel, 'file_action_notice')
            assert notice is not None and 'Convert your inputs' in notice.text()
        finally:
            dialog.reject()

    QTimer.singleShot(0, inspect)
    assert not manage_files(empty)


def test_backup_buttons_follow_selection_count(current_window: tuple[FitsMainWindow, Path], tmp_path: Path) -> None:
    """
    Offer restoring exactly one snapshot and deleting one or multiple snapshots.
    """
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QPushButton
    from fits.gui.file_management.manager import _history_panel
    from fits.workflows.file_management.history import Snapshot

    entries = tuple(Snapshot(tmp_path / str(index), tmp_path, (), ()) for index in range(2))
    group, history, _ = _history_panel(entries, tmp_path, lambda action: None)
    try:
        buttons = {button.text(): button for button in group.findChildren(QPushButton)}
        restore = buttons['Restore selected backup…']
        delete = buttons['Delete selected backups…']
        assert not restore.isEnabled() and not delete.isEnabled()
        history.setCurrentRow(0)
        assert restore.isEnabled() and delete.isEnabled()
        history.setCurrentRow(1, QItemSelectionModel.SelectionFlag.Select)
        assert not restore.isEnabled() and delete.isEnabled()
        history.clearSelection()
        assert not restore.isEnabled() and not delete.isEnabled()
    finally:
        group.close()
        group.deleteLater()


def test_moved_master_tags_warn_and_enable_only_location_update(current_window: tuple[FitsMainWindow, Path],
                                                                 tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch,
                                                                 ) -> None:
    """
    Show master location differences in the main GUI and clear them through Update.
    """
    import shutil
    import pandas as pd
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QDialog, QGroupBox, QPushButton
    from fits.gui.file_management.manager import manage_files
    from fits.gui.main_window.run_browser import OUTDATED_COLOR
    from fits.tasks.analysis.aggregate import save_master_analysis_table
    from fits.tasks.common.table_results import save_parquet
    from fits.workflows.artifacts.provenance import read_metadata

    window, series = current_window
    state = discover_saved_states(tmp_path)[0]
    raw = series / cst.FITS_ARRAY_RAW
    segmentation = series / cst.FITS_MASK_SEG
    mask_payload = read_metadata(raw).with_fitsio(artifact_type=cst.ARTI_SEG).new_revision([
        {'artifact_path': raw.name, 'created_at': read_metadata(raw).fits_io.created_at}])
    FitsIO.from_path(raw).save_array(np.ones((8, 8), dtype=np.uint16), output_path=segmentation, metadata=mask_payload)
    state = state.with_complete_step(step_name=cst.StepName.SEGMENT, artifact_kind=cst.ARTI_SEG, artifact_path=segmentation)
    payload = read_metadata(raw).with_fitsio(artifact_type=cst.ARTI_QUANTI).new_revision([
        {'artifact_path': raw.name, 'created_at': read_metadata(raw).fits_io.created_at},
        {'artifact_path': segmentation.name, 'created_at': mask_payload.fits_io.created_at}])
    table = series / cst.FITS_QUANTI_NAME
    save_parquet(pd.DataFrame({'object_name': ['segmentation'], 'object_channel': ['Red'],
                               'label': [1], 'frame': [0], 'intensity_mean': [5.0]}), table, payload)
    state = state.with_complete_step(step_name=cst.StepName.EXTRACT, artifact_kind=cst.ARTI_QUANTI, artifact_path=table)
    save_experiment_state(state)
    save_master_analysis_table([state], tmp_path, artifact_kind=cst.ARTI_QUANTI, output_name=cst.MASTER_QUANTI_NAME)
    before = table.read_bytes()
    moved = tmp_path / 'treated' / 'image'
    moved.parent.mkdir()
    shutil.move(series.parent, moved)
    window._refresh_run_inventory()
    assert not window._run_status.outdated
    assert not window._artifact_report.conflicts
    assert window.file_status_label.text() == 'Paths or condition tags need updating'
    assert OUTDATED_COLOR in window.file_status_label.styleSheet()
    assert 'Update paths and condition tags' in window._file_details_text()
    index = window.run_browser.model.index(str(moved / series.name))
    assert window.run_browser.model.data(index, Qt.ItemDataRole.ForegroundRole).name() == OUTDATED_COLOR
    monkeypatch.setattr('fits.gui.file_management.manager.confirm_files', lambda *args, **kwargs: True)

    def choose() -> None:
        """
        Inspect the three action controls and accept the enabled location repair.
        """
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        try:
            panel = next(group for group in dialog.findChildren(QGroupBox) if group.title() == 'Experiment files')
            buttons = {button.text(): button for button in panel.findChildren(QPushButton)}
            assert len(buttons) == 3
            assert not buttons['Rebuild results…'].isEnabled()
            assert buttons['Update paths and condition tags…'].isEnabled()
            buttons['Update paths and condition tags…'].click()
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, choose)
    assert manage_files(tmp_path, parent=window)
    window._refresh_run_inventory()
    assert not window._location_report.needs_update
    assert window.file_status_label.text() == 'Current — editable'
    assert (moved / series.name / table.name).read_bytes() == before


def test_outdated_run_offers_one_targeted_rebuild(current_window: tuple[FitsMainWindow, Path], tmp_path: Path) -> None:
    """
    Offer only targeted rebuilding after overwriting one stage without downstream work.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QGroupBox, QPushButton
    from fits.gui.file_management.manager import manage_files
    from fits.workflows.artifacts.provenance import read_metadata
    from fits_io.writers.metadata_update import rewrite_metadata

    window, series = current_window
    state = discover_saved_states(tmp_path)[0]
    raw = series / cst.FITS_ARRAY_RAW
    bg = series / cst.FITS_ARRAY_BGSUB
    reader = FitsIO.from_path(raw)
    payload = read_metadata(raw).with_fitsio(artifact_type=cst.ARTI_IMG_BGSUB).new_revision([
        {'artifact_path': raw.name, 'created_at': read_metadata(raw).fits_io.created_at}])
    reader.save_array(reader.get_array().array, metadata=payload, output_path=bg)
    save_experiment_state(state.with_complete_step(step_name=cst.StepName.BG_SUB, artifact_kind=cst.ARTI_IMG_BGSUB, artifact_path=bg))
    rewrite_metadata(raw, read_metadata(raw).new_revision())

    def inspect() -> None:
        """
        Check the dynamic title and prevent a second full-rebuild action.
        """
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        try:
            panel = next(group for group in dialog.findChildren(QGroupBox) if group.title() == 'Experiment files')
            buttons = {button.text(): button for button in panel.findChildren(QPushButton)}
            assert len(buttons) == 3
            assert buttons['Rebuild outdated results…'].isEnabled()
            assert not buttons['Update paths and condition tags…'].isEnabled()
        finally:
            dialog.reject()

    QTimer.singleShot(0, inspect)
    assert not manage_files(tmp_path, parent=window)
