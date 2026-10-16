from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from fits.gui.channel_labels import ChannelLabelsWindow
from fits.gui.main_window.window import FitsMainWindow
from fits.settings.loader import run_settings_path
from fits.gui.settings import SettingsAdapter
from fits_io import FitsIO


def test_main_window_channel_tool_order_and_run_wide_editor(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    source = experiment / "input.tif"
    pixels = np.zeros((2, 8, 9), dtype=np.uint8)
    tifffile.imwrite(source, pixels, imagej=True, metadata={"axes": "TYX"})
    FitsIO.from_path(source).save_array(
        pixels, channel_labels="GFP", output_path=experiment / "fits_array.tif")
    settings = run_settings_path(tmp_path)
    settings.parent.mkdir()
    settings.write_text('[convert.params]\nchannel_labels = ["GFP"]\n')
    adapter = SettingsAdapter()
    adapter.load(settings)
    window = FitsMainWindow(adapter)
    editor: ChannelLabelsWindow | None = None
    try:
        layout = window.run_browser.selection_layout
        labels = []
        for index in range(3):
            item = layout.itemAt(index)
            assert item is not None
            button = item.widget()
            assert isinstance(button, QPushButton)
            labels.append(button.text())
        assert labels == [
            "Tracking Viewer", "Channel Labels", "Full Report"]
        window.run_dir_edit.setText(str(tmp_path))
        assert window.channel_labels_button.isEnabled()
        window.channel_labels_button.click()
        assert window.adapter.run_dir == str(tmp_path)
        editor = window._channel_labels_window
        assert isinstance(editor, ChannelLabelsWindow)
        for _ in range(100):
            app.processEvents()
            if editor.plan is not None:
                break
            QTest.qWait(10)
        assert editor.plan is not None
        assert editor.plan.run_dir == tmp_path
        assert editor._fields[0].text() == "GFP"
        assert editor.files.toPlainText() == (
            f"Scanned {len(editor.plan.files)} FITS files.\n\n"
            "No files need updating.")
        app.processEvents()
        assert editor.status.y() > editor.save_button.y()
        status_height = editor.status.height()
        files_geometry = editor.files.geometry()
        editor.status.setText("A longer status message " * 20)
        app.processEvents()
        assert editor.status.height() == status_height
        assert editor.files.geometry() == files_geometry
        file_count = len(editor.plan.files)
        editor._fields[0].setText("Green")
        assert "experiment/fits_array.tif" in editor.files.toPlainText()
        editor.save_button.click()
        assert not editor.rename_progress.isHidden()
        assert editor.rename_progress.maximum() == 0
        for _ in range(150):
            app.processEvents()
            if window.adapter.document["convert"]["params"]["channel_labels"] == ["Green"]:
                break
            QTest.qWait(10)
        assert FitsIO.from_path(experiment / "fits_array.tif").channel_labels == ["Green"]
        assert window.adapter.document["convert"]["params"]["channel_labels"] == ["Green"]
        assert editor.rename_progress.maximum() == file_count
        assert editor.rename_progress.value() == file_count
        for _ in range(100):
            app.processEvents()
            if editor.rename_progress.isHidden():
                break
            QTest.qWait(10)
        assert editor.rename_progress.isHidden()
    finally:
        if editor is not None and editor._job is not None:
            for _ in range(100):
                app.processEvents()
                if not editor._job.isRunning():
                    break
                QTest.qWait(10)
        window.close()


def test_editor_previews_only_files_with_changed_channel(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    source = experiment / "input.tif"
    raw = np.zeros((2, 2, 8, 9), dtype=np.uint8)
    tifffile.imwrite(source, raw, imagej=True, metadata={"axes": "TCYX"})
    array_path = FitsIO.from_path(source).save_array(
        raw, channel_labels=["BFP", "RFP"],
        output_path=experiment / "fits_array.tif")
    FitsIO.from_path(array_path).save_array(
        raw[:, 1], export_channels=["RFP"],
        output_path=experiment / "fits_mask.tif")
    settings = run_settings_path(tmp_path)
    settings.parent.mkdir()
    settings.write_text('[convert.params]\nchannel_labels = ["BFP", "RFP"]\n')
    editor = ChannelLabelsWindow(tmp_path)
    editor.show()
    try:
        for _ in range(100):
            app.processEvents()
            if editor.plan is not None:
                break
            QTest.qWait(10)
        assert editor.plan is not None
        assert editor.files.toPlainText() == (
            f"Scanned {len(editor.plan.files)} FITS files.\n\n"
            "No files need updating.")
        editor._fields[0].setText("Blue")
        preview = editor.files.toPlainText()
        assert "fits_array.tif" in preview
        assert "fits_settings.toml" in preview
        assert "fits_mask.tif" not in preview
        assert editor.save_button.isEnabled()
    finally:
        for _ in range(100):
            app.processEvents()
            if editor._job is None or not editor._job.isRunning():
                break
            QTest.qWait(10)
        editor.close()


def test_editor_stays_visible_when_inspection_fails(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    editor = ChannelLabelsWindow(tmp_path)
    editor.show()
    try:
        for _ in range(100):
            app.processEvents()
            if editor.status.text() == "Could not inspect channel labels.":
                break
            QTest.qWait(10)
        assert editor.isVisible()
        assert editor.status.text() == "Could not inspect channel labels."
        assert "No FITS TIFFs" in editor.files.toPlainText()
    finally:
        if editor._job is not None:
            editor._job.wait(3000)
        editor.close()
