import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import numpy as np
import pytest
import tifffile
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from fits.gui.viewer.collection_window import MaskCollectionRequest, MaskCollectionWindow
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
    assert window.tool_tabs.tabBar().isHidden()
    assert window._kind() == 'reference'


def test_switch_cancel_preserves_and_ok_discards(window, tmp_path, monkeypatch):
    window.enqueue_experiment(request(tmp_path))
    mask = np.ones((8, 8), dtype=np.uint8)
    window._reference_session.set_mask_plane(mask)
    window._display_selection()
    monkeypatch.setattr(window, '_confirm', lambda *args: False)
    window.switch_mode('roi')
    assert window._kind() == 'reference'
    np.testing.assert_array_equal(window._reference_session.mask_plane(), mask)
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window.switch_mode('roi')
    assert window._kind() == 'roi'
    assert not window._reference_session.mask_array.any()
    window.switch_mode('reference')
    assert window._kind() == 'reference'


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
    assert 'Distance profiling cannot run' in warnings[0]
    assert 'whole image' in warnings[0]


def test_finish_drawing_is_not_cancellation(window, tmp_path, monkeypatch):
    window.enqueue_experiment(request(tmp_path))
    window.enqueue_experiment(request(tmp_path, 'b'))
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    finished, cancelled, outcomes = [], [], []
    window.collection_finished.connect(lambda: finished.append(True))
    window.cancellation_requested.connect(lambda: cancelled.append(True))
    window.experiment_finalized.connect(outcomes.append)
    window._finish_drawing()
    assert finished == [True]
    assert cancelled == []
    assert len(outcomes) == 2
    assert window._active is None
    assert window._ended


def test_quit_requires_confirmation(window, monkeypatch):
    cancelled = []
    window.cancellation_requested.connect(lambda: cancelled.append(True))
    monkeypatch.setattr(window, '_confirm', lambda *args: False)
    assert not window.close()
    assert cancelled == []
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    assert window.close()
    assert cancelled == [True]


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


def test_hidden_tab_shortcut_cannot_bypass_switch_buttons(window, tmp_path):
    window.enqueue_experiment(request(tmp_path))
    window.show()
    window.activateWindow()
    _APP.processEvents()
    window.image_viewer.setFocus()
    QTest.keyClick(window.image_viewer, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    assert window._kind() == 'reference'


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


def test_finish_mode_does_not_lock_switching(window, tmp_path, monkeypatch):
    window.enqueue_experiment(request(tmp_path))
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window._finish_mode()
    assert 'reference' in window._finished_modes
    window.switch_mode('roi')
    assert window._kind() == 'roi'
    window.switch_mode('reference')
    assert window.reference_panel.isEnabled()
    assert window.image_viewer.isEnabled()


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


def test_click_saved_mask_reloads_it_with_cancel_protection(window, tmp_path, monkeypatch):
    req = request(tmp_path)
    path = save_reference(req)
    window.enqueue_experiment(req)
    window._new_mask()
    assert not window._reference_session.mask_array.any()
    window.reference_panel.label_edit.setText('unsaved label')
    item = window.experiment_tree.topLevelItem(0).child(0)
    monkeypatch.setattr(window, '_confirm', lambda *args: False)
    window._tree_mask_selected(item)
    assert window.reference_panel.label_edit.text() == 'unsaved label'
    monkeypatch.setattr(window, '_confirm', lambda *args: True)
    window._tree_mask_selected(item)
    assert window._reference_path == path
    assert window.reference_panel.label_edit.text() == 'edge'
    assert window._reference_session.mask_array.any()
    assert len(window._saved['reference']) == 1


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


def test_control_buttons_have_tooltips_and_switch_label_follows_mode(window, tmp_path):
    window.enqueue_experiment(request(tmp_path))
    for button in (window.load_button, window.switch_button, window.return_button,
                   *window.expected_buttons.values(),
                   window.finish_mode_button, window.next_button, window.finish_button, window.quit_button):
        assert button.toolTip()
    assert window.switch_button.text() == 'Go to ROI'
    window.switch_button.click()
    assert window.switch_button.text() == 'Go to ref'
    assert window.finish_mode_button.text() == 'Finish ROI masks'
    window.show()
    _APP.processEvents()
    assert window.finish_mode_button.y() == window.next_button.y()
    assert window.finish_button.y() < window.quit_button.y()
    assert window.finish_button.x() == window.quit_button.x()


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
    assert window.switch_button.text() == 'Go to ref'


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
    window.cancellation_requested.connect(lambda: cancelled.append(True))
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
    assert window._ended
    assert not window.isVisible()


def test_expected_count_controls_preserve_drawings_and_required_reference(window, tmp_path):
    window.enqueue_experiment(request(tmp_path))
    session = window._reference_session
    session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    window.reference_panel.label_edit.setText('unfinished')
    window.expected_buttons['reference', 1].click()
    assert window._targets['reference'] == 2
    window.expected_buttons['reference', -1].click()
    assert window._targets['reference'] == 1
    assert not window.expected_buttons['reference', -1].isEnabled()
    window.expected_buttons['roi', 1].click()
    assert window._targets['roi'] == 1
    window.expected_buttons['roi', -1].click()
    assert window._targets['roi'] == 0
    assert session.mask_array.any()
    assert window.reference_panel.label_edit.text() == 'unfinished'
    assert 'skipped' not in window.count_label.text()
