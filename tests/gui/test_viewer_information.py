"""Consistent viewer help, action placement, and destructive shortcut scope."""
from pathlib import Path
from typing import cast

import numpy as np
import pytest
import tifffile
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication

from fits.gui.viewer.common.information_dialog import ViewerInformationDialog
from fits.gui.viewer.masks.window import MaskDrawingWindow
from fits.gui.viewer.segmentation.window import SegmentationTunerWindow
from fits.gui.viewer.tracking.window import TrackingViewerWindow

_APP: QApplication | None = None


def app() -> QApplication:
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    return _APP


def test_help_tables_keep_all_tool_controls_and_filter_by_function():
    app()
    for viewer in (MaskDrawingWindow, SegmentationTunerWindow, TrackingViewerWindow):
        dialog = ViewerInformationDialog(title='test', version='test', gui=viewer.help_gui, rows=viewer.tool_help, selection_enabled=True, editing_enabled=False)
        try:
            assert dialog.table.rowCount() > 0
            assert dialog.table.isColumnHidden(2)
            assert dialog.table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
            first = dialog.table.item(0, 1)
            assert first is not None
            dialog.search.setText(first.text().upper())
            assert not dialog.table.isRowHidden(0)
            dialog.search.setText('no such function')
            assert all(dialog.table.isRowHidden(row) for row in range(dialog.table.rowCount()))
            dialog.search.clear()
            assert all(not dialog.table.isRowHidden(row) for row in range(dialog.table.rowCount()))
        finally:
            dialog.close()


@pytest.mark.parametrize("gui", ["REF / ROI", "SegTune", "RegTune", "Tracking"])
def test_shared_help_catalog_filters_current_gui_and_consolidates_shortcuts(gui):
    app()
    dialog = ViewerInformationDialog(title="test", version="test", gui=gui)
    try:
        table = dialog.table
        assert table.columnCount() == 4
        assert table.isColumnHidden(2)
        rows = []
        for row in range(table.rowCount()):
            cells = [table.item(row, column) for column in range(4)]
            rows.append(tuple(cell.text() for cell in cells if cell is not None))
        shortcuts = [row[0] for row in rows]
        assert shortcuts.count("S") == 1
        assert shortcuts.count("Ctrl+Z") == (0 if gui in ("SegTune", "RegTune") else 1)
        assert ("R" in shortcuts) == (gui in ("SegTune", "RegTune"))
        assert sum(row[1] == "Next / previous Z plane" for row in rows) == 1
        assert all(row[2] == "All viewers" or set(gui.split(" / ")).intersection(
            row[2].split(" / ")) for row in rows)
        movement = [row for row in rows if row[0].startswith("Shift+")]
        assert len(movement) == (1 if gui == "REF / ROI" else 0)
        for shortcut in shortcuts:
            if "click" in shortcut.casefold():
                assert "left" in shortcut.casefold() or "right" in shortcut.casefold()
        assert "Left click mask or centroid" not in shortcuts
        dialog.search.setText("no such function")
        assert all(table.isRowHidden(row) for row in range(table.rowCount()))
    finally:
        dialog.close()


def test_read_only_tracking_help_only_lists_available_selection_controls():
    app()
    dialog = ViewerInformationDialog(title="test", version="test", gui="Tracking",
                                     editing_enabled=False, selection_enabled=True)
    try:
        shortcuts = []
        for row in range(dialog.table.rowCount()):
            item = dialog.table.item(row, 0)
            assert item is not None
            shortcuts.append(item.text())
        assert "Ctrl+left click mask or centroid" in shortcuts
        assert "Left click mask or centroid" not in shortcuts
        assert not {"S", "Ctrl+Z", "Ctrl+D", "Ctrl+Shift+D"}.intersection(shortcuts)
    finally:
        dialog.close()


@pytest.mark.parametrize('roi', [False, True])
def test_top_actions_and_clear_shortcuts_use_active_mask(tmp_path: Path, monkeypatch, roi: bool):
    app()
    source = tmp_path / 'fits_array.tif'
    tifffile.imwrite(source, np.zeros((3, 20, 22), dtype=np.uint16),
                     imagej=True, metadata={'axes': 'TYX'})
    window = MaskDrawingWindow()
    window._open_source(source)
    panel = window.roi_panel if roi else window.reference_panel
    window.tool_tabs.setCurrentWidget(panel)
    session = window._roi_session if roi else window._reference_session
    assert session is not None
    for frame in range(3):
        mask = np.zeros((20, 22), dtype=np.uint8)
        mask[3:6, 4:7] = 3 if roi else 1
        session.set_mask_plane(mask, frame_index=frame)
    window._display_selection()
    try:
        top = panel.controls_layout.itemAt(0)
        assert top is not None and top.widget() is panel.action_section
        assert panel.outer_layout.indexOf(panel.title_label) == 0
        assert panel.outer_layout.indexOf(panel.description_label) == 1
        assert panel.action_row.parentWidget() is panel.action_section
        assert panel.undo_button.parentWidget() is panel.action_row
        assert panel.clear_button.parentWidget() is panel.action_row
        assert panel.clear_all_button.parentWidget() is panel.action_row
        actions = panel.action_row.layout()
        assert actions is not None
        assert actions.indexOf(panel.undo_button) == 1
        assert actions.indexOf(panel.clear_button) == 2
        assert actions.indexOf(panel.clear_all_button) == 3
        monkeypatch.setattr(window, 'isActiveWindow', lambda: True)
        current = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
        assert window.eventFilter(window.image_viewer, current)
        assert not np.any(session.mask_plane(0))
        assert np.any(session.mask_plane(1))
        all_planes = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_D,
                              Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert window.eventFilter(window.image_viewer, all_planes)
        assert not np.any(session.mask_array)
        # Plain D remains a frame-navigation key.
        assert not window._tool_keypress(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_D, Qt.KeyboardModifier.NoModifier))
    finally:
        window.close()
