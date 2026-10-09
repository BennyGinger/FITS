"""Brush, mask translation, and preview-loading interaction contracts."""
from pathlib import Path
from typing import cast

import numpy as np
import pytest
import tifffile
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from fits.gui.viewer.common.image_viewer import FitsImageViewer
from fits.gui.viewer.masks.window import MaskDrawingWindow

_APP: QApplication | None = None


def app() -> QApplication:
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    return _APP


@pytest.mark.parametrize('roi', [False, True])
def test_shift_move_preserves_other_regions_and_roi_threshold_with_undo(tmp_path: Path, roi: bool):
    app()
    source = tmp_path / 'fits_array.tif'
    tifffile.imwrite(source, np.zeros((2, 20, 22), dtype=np.uint16),
                     imagej=True, metadata={'axes': 'TYX'})
    window = MaskDrawingWindow()
    window._open_source(source)
    session = window._roi_session if roi else window._reference_session
    assert session is not None
    mask = np.zeros((20, 22), dtype=np.uint8)
    mask[3:6, 3:6] = 4 if roi else 1
    mask[12:14, 12:14] = 3 if roi else 1
    if roi:
        mask[15:17, 3:6] = 2
    session.set_mask_plane(mask)
    if roi:
        window.tool_tabs.setCurrentWidget(window.roi_panel)
    window._display_selection()
    viewer = window.image_viewer
    try:
        viewer._start_mask_move(4, 4)
        viewer._finish_mask_move(8, 7)
        actual = session.mask_plane()
        assert not np.any(actual[3:6, 3:6] >= (3 if roi else 1))
        assert np.all(actual[6:9, 7:10] == (3 if roi else 1))
        np.testing.assert_array_equal(actual[12:14, 12:14], mask[12:14, 12:14])
        if roi:
            assert np.all(actual[3:6, 3:6] == 2)  # Original threshold retained, manually excluded.
            np.testing.assert_array_equal(actual[15:17, 3:6], mask[15:17, 3:6])
        window._undo_reference_drawing()
        np.testing.assert_array_equal(session.mask_plane(), mask)
    finally:
        window.close()


class MouseEvent:
    def __init__(self, x, y, *, shift=False, start=False, finish=False):
        self.position = QPointF(x, y)
        self.shift, self.start, self.finish = shift, start, finish
    def button(self):
        return Qt.MouseButton.LeftButton
    def modifiers(self):
        return Qt.KeyboardModifier.ShiftModifier if self.shift else Qt.KeyboardModifier.NoModifier
    def pos(self):
        return self.position
    def buttonDownPos(self):
        return self.position
    def isStart(self):
        return self.start
    def isFinish(self):
        return self.finish
    def accept(self):
        pass
    def ignore(self):
        pytest.fail('mask gesture was ignored')


def test_shift_click_selects_without_edit_and_plain_drag_moves_selection():
    app()
    viewer = FitsImageViewer()
    viewer.enable_mask_movement()
    mask = np.zeros((20, 22), dtype=np.uint8)
    mask[3:6, 3:6] = 1
    viewer.set_drawing_mask(mask)
    started = []
    committed = []
    viewer.drawing_started.connect(lambda: started.append(True))
    viewer.mask_moved.connect(lambda moved, before: committed.append(moved))
    try:
        viewer.drawing_item.mouseClickEvent(MouseEvent(4, 4, shift=True))
        assert viewer._move_region_hit(4, 4)
        assert started == committed == []
        viewer.drawing_item.mouseDragEvent(MouseEvent(4, 4, start=True))
        viewer.drawing_item.mouseDragEvent(MouseEvent(8, 7, finish=True))
        assert len(started) == len(committed) == 1
        expected = np.zeros_like(mask)
        expected[6:9, 7:10] = 1
        np.testing.assert_array_equal(viewer.drawing_mask, expected)
        viewer._start_mask_move(8, 7)
        viewer._finish_mask_move(100, 100)
        assert np.count_nonzero(viewer.drawing_mask) == np.count_nonzero(mask)
    finally:
        viewer.close()


def test_brush_is_a_stroke_and_polygon_fills_the_interior():
    app()
    viewer = FitsImageViewer()
    try:
        for tool in ('brush', 'freehand'):
            viewer.set_drawing_mask(np.zeros((30, 30), dtype=np.uint8))
            viewer.set_drawing_options('edit', tool, 'add', 1)
            viewer._start_drawing(5, 5)
            for x, y in ((22, 5), (22, 22), (5, 22)):
                viewer._continue_drawing(x, y)
            viewer._finish_drawing(5, 5)
            assert bool(viewer.drawing_mask[12, 12]) == (tool == 'freehand')
        window = MaskDrawingWindow()
        try:
            for panel in (window.reference_panel, window.roi_panel):
                assert panel.tool_combo.findData('brush') >= 0
                assert panel.tool_combo.itemText(panel.tool_combo.findData('freehand')) == 'Freehand polygon'
        finally:
            window.close()
    finally:
        viewer.close()


@pytest.mark.parametrize('roi', [False, True])
def test_clear_all_is_session_only_and_keeps_other_channels(tmp_path: Path, roi: bool):
    from fits_io import FitsIO
    from fits.tasks.reference_mask import ReferenceMaskSession
    from fits.tasks.roi_mask import RoiSession
    app()
    image = np.zeros((3, 2, 2, 20, 22), dtype=np.uint16)
    raw = tmp_path / 'raw.tif'
    tifffile.imwrite(raw, image, photometric='minisblack', metadata={'axes': 'TZCYX'})
    source = FitsIO.from_path(raw).save_array(
        image, channel_labels=('GFP', 'iRed'), output_path=tmp_path / 'fits_array.tif')
    session = RoiSession(source) if roi else ReferenceMaskSession(source)
    mask = np.zeros((20, 22), dtype=np.uint8)
    mask[3:6, 4:7] = 4 if roi else 1
    try:
        for channel in ('GFP', 'iRed'):
            for frame in range(3):
                for z in range(2):
                    session.set_mask_plane(mask, frame_index=frame, channel=channel, z_index=z)
            artifact = session.save('before', channel=channel)
    finally:
        session.close()
    before = artifact.read_bytes()
    window = MaskDrawingWindow()
    if roi:
        window.tool_tabs.setCurrentWidget(window.roi_panel)
        window._open_source(source, roi_path=artifact)
        button = window.roi_panel.clear_all_button
        cleared = window._roi_session
    else:
        window._open_source(source, reference_path=artifact)
        button = window.reference_panel.clear_all_button
        cleared = window._reference_session
    assert cleared is not None
    try:
        window.channel_combo.setCurrentText('GFP')
        button.click()
        for frame in range(3):
            for z in range(2):
                assert not np.any(cleared.mask_plane(frame, 'GFP', z))
                np.testing.assert_array_equal(cleared.mask_plane(frame, 'iRed', z), mask)
        assert artifact.read_bytes() == before
    finally:
        window.close()
    reopened = (RoiSession(source, roi_path=artifact) if roi
                else ReferenceMaskSession(source, reference_path=artifact))
    try:
        np.testing.assert_array_equal(reopened.mask_plane(2, 'GFP', 1), mask)
    finally:
        reopened.close()
