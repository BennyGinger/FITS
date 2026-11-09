import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import numpy as np
import pytest
import tifffile
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from fits.gui.viewer.masks.collection import (
    MaskCollectionRequest, MaskCollectionWindow,)
from fits.settings.models import DistanceProfileSettings, ExtractSettings

_APP = None


@pytest.fixture
def window(monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    w = MaskCollectionWindow(preview=True)
    yield w
    w._ended = True
    w.close()


def request(tmp_path, name='a'):
    folder = tmp_path / name
    folder.mkdir()
    source = folder / 'fits_array.tif'
    tifffile.imwrite(source, np.arange(128, dtype=np.uint16).reshape(2, 8, 8),
                     imagej=True, metadata={'axes': 'TYX'})
    return MaskCollectionRequest(name, source)


def test_queue_arrival_preserves_active_work(window, tmp_path):
    first = request(tmp_path)
    second = request(tmp_path, 'b')
    window.enqueue_experiment(first)
    window.reference_panel.label_edit.setText('work in progress')
    session = window._reference_session
    window.enqueue_experiment(second)
    window.enqueue_experiment(second)
    assert window._active == first
    assert window._reference_session is session
    assert window.reference_panel.label_edit.text() == 'work in progress'
    assert window.experiment_tree.topLevelItemCount() == 2
    assert not window.tool_tabs.tabBar().isHidden()
    assert window._kind() == 'reference'


def test_tab_switch_preserves_unsaved_drawing(window: MaskCollectionWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep each tab's draft when switching without a discard dialog.
    """
    window.enqueue_experiment(request(tmp_path))
    session = window._reference_session
    assert session is not None
    mask = np.ones((8, 8), dtype=np.uint8)
    session.set_mask_plane(mask)
    monkeypatch.setattr(window, '_confirm', lambda *args: pytest.fail('Unexpected discard warning'))
    window.switch_mode('roi')
    assert window._kind() == 'roi'
    window.switch_mode('reference')
    assert window._reference_session is session
    np.testing.assert_array_equal(session.mask_plane(), mask)
    assert window._dirty('reference')


def test_saved_mask_switches_without_warning_and_count_is_unique(window, tmp_path, monkeypatch):
    window.enqueue_experiment(request(tmp_path))
    window._reference_session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window._display_selection()
    window.reference_panel.label_edit.setText('edge')
    window._save_reference_mask()
    assert len(window._saved['reference']) == 1
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    window._save_reference_mask()
    assert len(window._saved['reference']) == 1
    def unexpected(*args):
        pytest.fail('A saved mask should not trigger a discard warning')
    monkeypatch.setattr(window, '_confirm', unexpected)
    window.switch_mode('roi')
    window.switch_mode('reference')
    assert window._reference_session.mask_array.any()


def test_next_experiment_reports_outcome_and_starts_reference(window, tmp_path, monkeypatch):
    window.enqueue_experiment(request(tmp_path))
    second = request(tmp_path, 'b')
    window.enqueue_experiment(second)
    window.switch_mode('roi')
    warnings = []
    monkeypatch.setattr(window, '_confirm', lambda title, message: warnings.append(message) or True)
    outcomes = []
    window.experiment_finalized.connect(outcomes.append)
    window._finish_experiment()
    assert window._active == second
    assert window._kind() == 'reference'
    assert outcomes[0].skipped_references == 1
    assert '1 expected reference mask(s) remain' in warnings[0]


def test_next_experiment_collapses_previous_tree_item(window, tmp_path, monkeypatch):
    first = request(tmp_path)
    second = request(tmp_path, 'b')
    window.enqueue_experiment(first)
    window.enqueue_experiment(second)
    first_item = window.experiment_tree.topLevelItem(0)
    assert first_item.isExpanded()
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window._finish_experiment()
    first_item = window.experiment_tree.topLevelItem(0)
    second_item = window.experiment_tree.topLevelItem(1)
    assert not first_item.isExpanded()
    assert second_item.isExpanded()


def test_next_waits_for_later_request_before_finishing_current(window, tmp_path, monkeypatch):
    window._preview = False
    first = request(tmp_path)
    window.enqueue_experiment(first)
    outcomes = []
    window.experiment_finalized.connect(outcomes.append)
    monkeypatch.setattr(window, '_confirm', lambda *args: True)

    window._refresh_collection()
    assert not window.next_button.isEnabled()

    window._finish_experiment()

    assert outcomes == []
    assert window._active == first

    second = request(tmp_path, 'b')
    window.enqueue_experiment(second)

    assert window.next_button.isEnabled()
    window._finish_experiment()

    first_item = window.experiment_tree.topLevelItem(0)
    second_item = window.experiment_tree.topLevelItem(1)
    assert window._active == second
    assert len(outcomes) == 1
    assert not first_item.isExpanded()
    assert second_item.isExpanded()


def test_pipeline_experiment_total_is_displayed(window, tmp_path):
    window.set_expected_experiments(12)
    window.enqueue_experiment(request(tmp_path))
    assert 'Experiment 1 of 12' in window.experiment_label.text()


def test_finish_drawing_is_not_cancellation(window, tmp_path, monkeypatch):
    window.enqueue_experiment(request(tmp_path))
    window.enqueue_experiment(request(tmp_path, 'b'))
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    finished, cancelled, outcomes = [], [], []
    window.collection_finished.connect(lambda: finished.append(True))
    window.experiment_finalized.connect(outcomes.append)
    window._finish_drawing()
    assert finished == [True]
    assert cancelled == []
    assert len(outcomes) == 2
    assert window._active is None
    assert window._ended


def test_close_finishes_collection_after_confirmation(window: MaskCollectionWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Close resolves mask requests without a pipeline cancellation action.
    """
    window.enqueue_experiment(request(tmp_path))
    finished: list[bool] = []
    window.collection_finished.connect(lambda: finished.append(True))
    monkeypatch.setattr(window, '_confirm', lambda *args: False)
    assert not window.close()
    assert not finished
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    assert window.close()
    assert finished == [True]
    assert not hasattr(window, 'cancellation_requested')


def test_empty_queue_distinguishes_waiting_from_complete(window):
    assert 'Waiting' in window.experiment_label.text()
    window.no_more_requests()
    assert 'All experiments finished' in window.experiment_label.text()


def test_requests_use_analysis_settings(tmp_path):
    r = MaskCollectionRequest.from_settings(tmp_path / 'fits_array.tif',
        extraction=ExtractSettings(draw_ref_mask=True, expected_ref_masks=3),
        profile=DistanceProfileSettings(draw_roi_mask=True, expected_roi_masks=2))
    assert r.expected_ref_masks == 3
    assert r.expected_roi_masks == 2
    assert r.requires_reference
    r = MaskCollectionRequest.from_settings(tmp_path / 'fits_array.tif', extraction=ExtractSettings())
    assert r.expected_ref_masks == r.expected_roi_masks == 0
    assert not r.requires_reference


def test_visible_tabs_allow_keyboard_navigation(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    Expose standard tabs and their keyboard navigation.
    """
    window.enqueue_experiment(request(tmp_path))
    window.show()
    QApplication.processEvents()
    QTest.keyClick(window.tool_tabs, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    assert window._kind() == 'roi'


def test_save_then_add_starts_empty_mask_without_changing_mode(window, tmp_path):
    window.enqueue_experiment(request(tmp_path))
    window._reference_session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window._display_selection()
    window.reference_panel.label_edit.setText('first')
    window._save_reference_mask()
    window._new_mask()
    assert window._kind() == 'reference'
    assert len(window._saved['reference']) == 1
    assert not window._reference_session.mask_array.any()
    assert window.reference_panel.label_edit.text() == ''


def test_empty_roi_tab_can_add_its_own_mask(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    A zero-count tab can start a new mask independently.
    """
    window.enqueue_experiment(request(tmp_path))
    window.switch_mode('roi')
    assert not window.saving_stack.isEnabled()
    window.add_mask_buttons['roi'].click()
    assert window._targets['roi'] == 1
    assert window.saving_stack.isEnabled()


def test_close_checks_missing_masks_in_both_tabs(window: MaskCollectionWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Closing from ROI also warns about the outstanding reference slot.
    """
    window.enqueue_experiment(request(tmp_path))
    window.switch_mode('roi')
    warnings: list[str] = []
    monkeypatch.setattr(window, '_confirm', lambda title, message: warnings.append(message) or False)
    assert not window.close()
    assert warnings
    assert not window._ended


def save_reference(req, label='edge'):
    from fits.tasks.reference_mask import ReferenceMaskSession
    session = ReferenceMaskSession(req.image_path)
    session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    return session.save(label)


def test_tree_shows_current_waiting_and_completed_experiments(window, tmp_path, monkeypatch):
    first, second = request(tmp_path), request(tmp_path, 'b')
    save_reference(first)
    save_reference(second, 'other')
    window.enqueue_experiment(first)
    window.enqueue_experiment(second)
    tree = window.experiment_tree
    assert tree.topLevelItemCount() == 2
    assert 'current' in tree.topLevelItem(0).text(0)
    assert tree.topLevelItem(0).font(0).bold()
    assert tree.topLevelItem(0).child(0).text(0) == 'fits_ref_edge.tif'
    assert tree.topLevelItem(1).child(0).text(0) == 'fits_ref_other.tif'
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window._finish_experiment()
    assert 'finished' in tree.topLevelItem(0).text(0)
    assert 'current' in tree.topLevelItem(1).text(0)


def test_click_saved_mask_preserves_other_slot_draft(window: MaskCollectionWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Selecting a saved mask leaves a new slot's label and drawing intact.
    """
    req = request(tmp_path)
    path = save_reference(req)
    window.enqueue_experiment(req)
    window._new_mask()
    window.reference_panel.label_edit.setText('unsaved label')
    draft = window._reference_session
    parent = window.experiment_tree.topLevelItem(0)
    assert parent is not None
    item = parent.child(0)
    assert item is not None
    monkeypatch.setattr(window, '_confirm', lambda *args: pytest.fail('Unexpected discard warning'))
    window._tree_mask_selected(item)
    assert window._reference_path == path
    assert window.reference_panel.label_edit.text() == 'edge'
    window._select_mask_slot('reference', 1)
    assert window.reference_panel.label_edit.text() == 'unsaved label'
    assert window._reference_session is draft
    assert window._dirty('reference')


def test_other_experiment_mask_can_be_viewed_without_losing_current_drawing(window, tmp_path):
    first, second = request(tmp_path), request(tmp_path, 'b')
    save_reference(second)
    window.enqueue_experiment(first)
    window.enqueue_experiment(second)
    window.reference_panel.label_edit.setText('unfinished')
    session = window._reference_session
    session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window._display_selection()
    window._tree_mask_selected(window.experiment_tree.topLevelItem(1).child(0))
    assert window._inspection is not None
    assert window._active == first
    assert window._reference_session is session
    assert not window.tool_panel.isEnabled()
    assert window.return_button.isVisibleTo(window)
    window._return_to_current()
    assert window._inspection is None
    assert window._active == first
    assert window.reference_panel.label_edit.text() == 'unfinished'
    assert session.mask_array.any()
    assert window.tool_panel.isEnabled()


def test_collection_actions_match_segtune_and_stack_below_save(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    Keep saving, navigation and close in the agreed visual order.
    """
    window.enqueue_experiment(request(tmp_path))
    for button in (window.load_button, window.return_button, window.next_button,
                   window.close_button, window.reference_panel.save_button):
        assert button.toolTip()
    window.show()
    QApplication.processEvents()
    assert not window.tool_tabs.tabBar().isHidden()
    assert window.saving_stack.y() < window.next_button.y() < window.close_button.y()
    assert window.close_button.text() == 'Close window'
    assert '#16803b' in window.reference_panel.save_button.styleSheet()
    assert '#d97706' in window.next_button.styleSheet()
    assert '#e8a0a0' in window.close_button.styleSheet()
    assert not hasattr(window, 'switch_button')
    assert not hasattr(window, 'quit_button')


def test_integrated_window_has_no_manual_experiment_loader():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    w = MaskCollectionWindow(preview=False)
    assert w.load_button.isHidden()
    assert w.preview_note.isHidden()
    w._ended = True
    w.close()


def test_saved_masks_appear_immediately_and_roi_click_selects_roi(window, tmp_path):
    from fits.tasks.roi_mask import RoiSession
    req = request(tmp_path)
    roi = RoiSession(req.image_path)
    roi.threshold_plane(10, 30)
    roi.save('region')
    window.enqueue_experiment(req)
    window._reference_session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window._display_selection()
    window.reference_panel.label_edit.setText('first')
    window._save_reference_mask()
    window._new_mask()
    window._reference_session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window._display_selection()
    window.reference_panel.label_edit.setText('second')
    window._save_reference_mask()
    window._new_mask()
    parent = window.experiment_tree.topLevelItem(0)
    assert [parent.child(i).text(0) for i in range(parent.childCount())] == [
        'fits_ref_first.tif', 'fits_ref_second.tif', 'fits_roi_region.tif']
    window._tree_mask_selected(parent.child(2))
    assert window._kind() == 'roi'
    assert window.roi_panel.label_edit.text() == 'region'
    assert window._roi_session.display_mask_plane().any()
    assert window.tool_tabs.currentWidget() is window.roi_panel


def test_reference_label_suggestion_uses_first_alphabetical_previous_mask(window, tmp_path, monkeypatch):
    first, second = request(tmp_path), request(tmp_path, 'b')
    save_reference(first, 'zebra')
    save_reference(first, 'alpha')
    window.enqueue_experiment(first)
    window.enqueue_experiment(second)
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window._finish_experiment()
    assert window.reference_panel.label_edit.text() == 'alpha'
    assert not window._reference_session.mask_array.any()
    assert not window._dirty('reference')
    window.switch_mode('roi')
    window.switch_mode('reference')
    assert window.reference_panel.label_edit.text() == 'alpha'
    assert window._targets['reference'] == second.expected_ref_masks


def test_existing_reference_label_takes_precedence_over_suggestion(window, tmp_path, monkeypatch):
    first, second = request(tmp_path), request(tmp_path, 'b')
    save_reference(first, 'alpha')
    save_reference(second, 'existing')
    window.enqueue_experiment(first)
    window.enqueue_experiment(second)
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window._finish_experiment()
    assert window.reference_panel.label_edit.text() == 'existing'


def test_collection_modes_have_different_dark_backgrounds(window, tmp_path):
    from PySide6.QtGui import QPalette
    window.enqueue_experiment(request(tmp_path))
    reference = window.centralWidget().palette().color(QPalette.ColorRole.Window)
    window.switch_mode('roi')
    roi = window.centralWidget().palette().color(QPalette.ColorRole.Window)
    assert reference != roi
    assert reference.lightness() < 65 and roi.lightness() < 65
    assert 'ROI' in window.mode_label.text()


def test_roi_label_suggestion_keeps_previous_saved_name(window, tmp_path, monkeypatch):
    from fits.tasks.roi_mask import RoiSession
    first, second = request(tmp_path), request(tmp_path, 'b')
    roi = RoiSession(first.image_path)
    roi.threshold_plane(10, 30)
    roi.save('tail')
    window.enqueue_experiment(first)
    window.enqueue_experiment(second)
    window.switch_mode('roi')
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window._finish_experiment()
    window.switch_mode('roi')
    assert window.roi_panel.label_edit.text() == 'tail'
    assert not window._roi_session.mask_array.any()
    assert not window._dirty('roi')


@pytest.mark.parametrize("action", ["next", "finish"])
def test_completed_drawing_closes_without_warning(window, tmp_path, monkeypatch, action):
    req = request(tmp_path)
    save_reference(req, "reference")
    window.enqueue_experiment(req)
    window.no_more_requests()
    window.show()
    finished, cancelled = [], []
    window.collection_finished.connect(lambda: finished.append(True))
    monkeypatch.setattr(window, '_confirm', lambda *args: pytest.fail("Unexpected warning"))
    if action == "next":
        window._finish_experiment()
    else:
        window._finish_drawing()
    assert window._ended
    assert not window.isVisible()
    assert finished == [True]
    assert not cancelled


def test_experiment_names_are_relative_and_tree_stays_flat(window, tmp_path):
    window.run_dir = tmp_path
    condition = tmp_path / "condition"
    condition.mkdir()
    req = request(condition)
    save_reference(req, "reference")
    window.enqueue_experiment(req)
    tree = window.experiment_tree
    assert tree.topLevelItemCount() == 1
    parent = tree.topLevelItem(0)
    assert parent.text(0) == "condition/a — current"
    assert parent.child(0).text(0) == "fits_ref_reference.tif"
    assert not hasattr(window, "save_next_button")


def test_empty_queue_waits_until_pipeline_has_sent_all_requests(window, tmp_path, monkeypatch):
    window._preview = False
    req = request(tmp_path)
    save_reference(req, "reference")
    window.enqueue_experiment(req)
    window.show()
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window._finish_experiment()
    assert not window._ended
    assert window.isVisible()
    window.no_more_requests()
    assert window.next_button.isEnabled()
    window._finish_experiment()
    assert window._ended
    assert not window.isVisible()


def test_deleting_placeholder_can_reduce_required_count_to_zero(window: MaskCollectionWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Empty placeholders are removable without a warning, including the last REF.
    """
    window.enqueue_experiment(request(tmp_path))
    monkeypatch.setattr(window, '_confirm', lambda *args: pytest.fail('Empty slot deletion warned'))
    window._delete_mask('reference', 0)
    assert window._targets['reference'] == 0
    assert window.mask_lists['reference'].count() == 0
    assert not window.saving_stack.isEnabled()
    window.add_mask_buttons['reference'].click()
    assert window._targets['reference'] == 1
    assert window.saving_stack.isEnabled()


def test_saved_session_dirty_check_avoids_full_stack_copy(window, tmp_path, monkeypatch):
    window.enqueue_experiment(request(tmp_path))
    session = window._reference_session
    session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window.reference_panel.label_edit.setText('ref')
    window._saved_mask('reference', tmp_path / 'fits_ref_ref.tif')
    def unexpected(*args, **kwargs):
        pytest.fail('unchanged-session check assembled the full mask stack')
    monkeypatch.setattr(session._mask, 'copy', unexpected)
    assert not window._dirty('reference')
    assert '#16803b' in window.reference_panel.save_button.styleSheet()


def test_next_experiment_does_not_copy_stacks_or_read_later_frames(window, tmp_path, monkeypatch):
    from fits.interaction.planes import PlaneStore

    first, second = request(tmp_path), request(tmp_path, 'b')
    window.enqueue_experiment(first)
    window.enqueue_experiment(second)
    monkeypatch.setattr(window, '_confirm', lambda *args: True)

    def unexpected_copy(*args, **kwargs):
        pytest.fail('Next experiment copied a whole stack')

    original_plane = PlaneStore.plane
    def current_plane(self, frame=0, channel=0, z=0):
        assert frame == 0, 'Next experiment eagerly read a later frame'
        return original_plane(self, frame, channel, z)

    monkeypatch.setattr(PlaneStore, 'copy', unexpected_copy)
    monkeypatch.setattr(PlaneStore, 'plane', current_plane)
    assert window._finish_experiment()
    assert window._active == second
    assert not window._dirty('reference')
    assert not window._dirty('roi')


@pytest.mark.parametrize('kind', ['reference', 'roi'])
def test_saved_baseline_survives_edits_and_restoring_pixels(window, tmp_path, kind):
    window.enqueue_experiment(request(tmp_path))
    session, panel = window._session_panel(kind)
    mask = np.ones((8, 8), dtype=np.uint8)
    session.set_mask_plane(mask)
    panel.label_edit.setText('test')
    window._saved_mask(kind, tmp_path / f'fits_{kind}_test.tif')
    session.set_mask_plane(np.zeros_like(mask))
    assert window._dirty(kind)
    session.set_mask_plane(mask)
    assert not window._dirty(kind)


def test_saving_one_channel_keeps_other_channel_dirty(window, tmp_path):
    folder = tmp_path / 'multi'
    folder.mkdir()
    source = folder / 'fits_array.tif'
    tifffile.imwrite(source, np.zeros((2, 2, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={'axes': 'TCYX'})
    window.enqueue_experiment(MaskCollectionRequest('multi', source))
    session = window._reference_session
    mask = np.ones((8, 8), dtype=np.uint8)
    session.set_mask_plane(mask, channel=0)
    session.set_mask_plane(mask, channel=1)
    window.channel_combo.setCurrentIndex(0)
    window._saved_mask('reference', folder / 'fits_ref_ref.tif')
    assert window._dirty('reference')


pytestmark = pytest.mark.usefixtures("current_format_tiffs")


@pytest.mark.parametrize('kind', ['reference', 'roi'])
def test_empty_label_save_is_clickable_and_reports_error(window: MaskCollectionWindow, tmp_path: Path, kind: str) -> None:
    """
    Empty labels cannot write a file and receive visible validation feedback.
    """
    window.enqueue_experiment(request(tmp_path))
    window.switch_mode(kind)
    if not window._slots[kind]:
        window._add_mask(kind)
    _, panel = window._session_panel(kind)
    panel.label_edit.setText('   ')
    assert panel.save_button.isEnabled()
    panel.save_button.click()
    assert '#ef6666' in panel.label_edit.styleSheet()
    assert '#ef6666' in window.status_label.styleSheet()
    assert 'compulsory' in window.status_label.text()
    assert not window._saved[kind]
    panel.label_edit.setText('wound')
    assert not panel.label_edit.styleSheet()


@pytest.mark.parametrize('kind', ['reference', 'roi'])
def test_saved_mask_deletion_requires_confirmation_and_removes_file(window: MaskCollectionWindow,
                                                                  tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch,
                                                                  kind: str,
                                                                  ) -> None:
    """
    The bin deletes the actual file only after accepting the permanent deletion.
    """
    from fits.tasks.roi_mask import RoiSession
    req = request(tmp_path)
    if kind == 'reference':
        path = save_reference(req)
    else:
        session = RoiSession(req.image_path)
        session.threshold_plane(10, 30)
        path = session.save('region')
    window.enqueue_experiment(req)
    window.switch_mode(kind)
    monkeypatch.setattr(window, '_confirm', lambda *args: False)
    window._delete_mask(kind, 0)
    assert path.is_file()
    assert window._targets[kind] == 1
    warnings: list[str] = []
    monkeypatch.setattr(window, '_confirm', lambda title, message: warnings.append(message) or True)
    window._delete_mask(kind, 0)
    assert not path.exists()
    assert window._targets[kind] == 0
    assert not window._saved[kind]
    assert window.mask_lists[kind].count() == 0
    assert path.name in warnings[0] and 'cannot be undone' in warnings[0]
    parent = window.experiment_tree.topLevelItem(0)
    assert parent is not None
    assert parent.childCount() == 0


def test_slot_selection_preserves_pixels_and_unsaved_state(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    Independent slots retain their masks, labels and dirty baselines.
    """
    window.enqueue_experiment(request(tmp_path))
    first = window._reference_session
    assert first is not None
    first.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window.reference_panel.label_edit.setText('first')
    window._drawing_started()
    window._new_mask()
    second = window._reference_session
    assert second is not None and second is not first
    assert not second.mask_plane().any()
    window.reference_panel.label_edit.setText('second')
    window.mask_lists['reference'].setCurrentRow(0)
    assert window._reference_session is first
    assert first.mask_plane().all()
    assert window.reference_panel.label_edit.text() == 'first'
    assert window._dirty('reference')
    window.mask_lists['reference'].setCurrentRow(1)
    assert window._reference_session is second
    assert window.reference_panel.label_edit.text() == 'second'
    assert window._dirty('reference')


def test_inactive_draft_warns_when_closing_other_tab(window: MaskCollectionWindow,
                                                   tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch,
                                                   ) -> None:
    """
    Closing from ROI still protects a parked REF drawing.
    """
    window.enqueue_experiment(request(tmp_path))
    session = window._reference_session
    assert session is not None
    session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window._new_mask()
    window.switch_mode('roi')
    warnings: list[str] = []
    monkeypatch.setattr(window, '_confirm', lambda title, message: warnings.append(message) or False)
    assert not window.close()
    assert any('unsaved changes will be lost' in message for message in warnings)
    assert not window._ended
    window.switch_mode('reference')
    window._select_mask_slot('reference', 0)
    assert session.mask_plane().all()


def test_placeholder_acquires_channel_and_label_on_drawing(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    The list starts with a numbered expectation and identifies a drawing channel.
    """
    from PySide6.QtWidgets import QPushButton
    window.enqueue_experiment(request(tmp_path))
    mask_list = window.mask_lists['reference']
    row = mask_list.itemWidget(mask_list.item(0))
    assert row is not None
    assert row.findChildren(QPushButton)[0].text() == 'Expected mask – 1'
    window._drawing_started()
    row = mask_list.itemWidget(mask_list.item(0))
    assert row is not None
    assert row.findChildren(QPushButton)[0].text() == f'{window.channel_combo.currentText()} – unlabelled'
    window.reference_panel.label_edit.setText('wound')
    row = mask_list.itemWidget(mask_list.item(0))
    assert row is not None
    assert row.findChildren(QPushButton)[0].text().endswith(' – wound')


def test_failed_file_deletion_preserves_slot(window: MaskCollectionWindow,
                                           tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch,
                                           ) -> None:
    """
    A filesystem error keeps the saved mask and its expected slot intact.
    """
    req = request(tmp_path)
    path = save_reference(req)
    window.enqueue_experiment(req)
    monkeypatch.setattr(window, '_confirm', lambda *args: True)

    def deny_delete(self: Path, missing_ok: bool = False) -> None:
        """
        Simulate a file deletion rejected by the filesystem.
        """
        raise PermissionError('read only')

    with monkeypatch.context() as context:
        context.setattr(Path, 'unlink', deny_delete)
        window._delete_mask('reference', 0)
    assert path.is_file()
    assert window._targets['reference'] == 1
    assert path in window._saved['reference']
    assert 'Could not delete' in window.status_label.text()


def test_saving_under_new_label_keeps_both_saved_files_listed(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    Saving a renamed copy retains the original file and its editing entry.
    """
    req = request(tmp_path)
    original = save_reference(req, 'first')
    window.enqueue_experiment(req)
    window.reference_panel.label_edit.setText('second')
    window._save_reference_mask()
    copy = original.with_name('fits_ref_second.tif')
    assert original.is_file() and copy.is_file()
    assert {slot.path for slot in window._slots['reference']} == {original, copy}
    assert window._targets['reference'] == 2
    assert not window._dirty('reference')


def test_overwriting_from_new_slot_keeps_one_entry_per_file(window: MaskCollectionWindow,
                                                          tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch,
                                                          ) -> None:
    """
    Overwriting a saved mask retains an outstanding expected slot.
    """
    req = request(tmp_path)
    path = save_reference(req, 'first')
    window.enqueue_experiment(req)
    window._new_mask()
    session = window._reference_session
    assert session is not None
    session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window.reference_panel.label_edit.setText('first')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    window._save_reference_mask()
    assert [slot.path for slot in window._slots['reference']].count(path) == 1
    assert window._targets['reference'] == 2
    assert len(window._saved['reference']) == 1
    assert window._slots['reference'][0].path is None


def test_thresholding_identifies_roi_slot_channel(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    Automatic masks identify their channel just like manually drawn masks.
    """
    window.enqueue_experiment(request(tmp_path))
    window.switch_mode('roi')
    window._new_mask()
    window.roi_panel.automatic_current_button.click()
    slot = window._current_slot('roi')
    assert slot is not None
    assert slot.channel == window.channel_combo.currentText()
    assert window._dirty('roi')


def test_zero_count_tab_stays_uneditable_after_navigation(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    Frame changes cannot reactivate drawing or saving in an empty tab.
    """
    from PySide6.QtGui import QKeyEvent
    window.enqueue_experiment(request(tmp_path))
    window.switch_mode('roi')
    window.frame_slider.setValue(1)
    assert not window.roi_panel.controls_scroll.isEnabled()
    assert not window.saving_stack.isEnabled()
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_S, Qt.KeyboardModifier.NoModifier)
    assert window._tool_keypress(event)
    assert not window._saved['roi']


def test_tab_colour_change_repaints_image(window: MaskCollectionWindow, tmp_path: Path) -> None:
    """
    Switching the surrounding palette must leave the source image visible.
    """
    window.enqueue_experiment(request(tmp_path))
    window.show()
    QApplication.processEvents()
    window.switch_mode('roi')
    QApplication.processEvents()
    canvas = window.image_viewer.canvas
    scene_point = window.image_viewer.image_item.mapToScene(7.0, 7.0)
    point = canvas.mapFromScene(scene_point)
    viewport = canvas.viewport()
    assert viewport is not None
    snapshot = viewport.grab().toImage()
    assert snapshot.pixelColor(point).lightness() > 200


@pytest.mark.parametrize('action', ['close', 'next'])
@pytest.mark.parametrize('accept', [True, False])
def test_missing_and_unsaved_masks_use_one_confirmation(window: MaskCollectionWindow,
                                                      tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      action: str,
                                                      accept: bool,
                                                      ) -> None:
    """
    One decision covers both tabs' missing masks, edits and queued requests.
    """
    window.enqueue_experiment(request(tmp_path))
    window.enqueue_experiment(request(tmp_path, 'second'))
    window.reference_panel.label_edit.setText('unfinished reference')
    window.switch_mode('roi')
    window._new_mask()
    window.roi_panel.label_edit.setText('unfinished roi')
    warnings: list[str] = []
    monkeypatch.setattr(window, '_confirm', lambda title, message: warnings.append(message) or accept)
    result = window.close() if action == 'close' else window._finish_experiment()
    assert result == accept
    assert len(warnings) == 1
    assert '1 expected reference mask(s)' in warnings[0]
    assert '1 expected roi mask(s)' in warnings[0]
    assert 'unsaved changes will be lost' in warnings[0]
    if not accept:
        assert window.roi_panel.label_edit.text() == 'unfinished roi'
        assert not window._ended


def test_unsaved_edits_without_missing_masks_still_warn_once(window: MaskCollectionWindow,
                                                           tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch,
                                                           ) -> None:
    """
    Existing saved masks do not suppress the warning about later edits.
    """
    req = request(tmp_path)
    save_reference(req)
    window.enqueue_experiment(req)
    window.reference_panel.label_edit.setText('edited label')
    warnings: list[str] = []
    monkeypatch.setattr(window, '_confirm', lambda title, message: warnings.append(message) or True)
    assert window.close()
    assert len(warnings) == 1
    assert 'unsaved changes will be lost' in warnings[0]
    assert 'expected' not in warnings[0]
