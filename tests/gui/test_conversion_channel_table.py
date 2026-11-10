"""Conversion table metadata, user labels and saved blank positions."""

import os
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QTableWidgetItem

from fisch.environment.constant import StepName
from fisch.gui.settings import SettingsAdapter, StepSettingsEditor
from fisch.gui.settings.conversion_channels import ConversionChannelsWidget
from fisch.workflows.checks.models import RawInputReport


@pytest.mark.parametrize("key", [Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_label_entry_advances_to_empty_names(key: Qt.Key) -> None:
    """Commit typed names, skip populated rows, wrap, and stop when complete."""
    app = QApplication.instance() or QApplication([])
    widget = ConversionChannelsWidget(["", "", "existing", ""])
    widget.set_source(4, None)
    widget.show()
    table = widget.table
    table.setCurrentCell(1, 2)
    table.editItem(table.item(1, 2))
    app.processEvents()
    try:
        for text, next_row in [("second", 3), ("fourth", 0), ("first", 0)]:
            editor = app.focusWidget()
            assert isinstance(editor, QLineEdit)
            QTest.keyClicks(editor, text)
            QTest.keyClick(editor, key)
            app.processEvents()
            assert table.currentRow() == next_row
            assert table.currentColumn() == 2
        assert widget.value() == ["first", "second", "existing", "fourth"]
        assert app.focusWidget() is table
    finally:
        widget.close()
        app.processEvents()


@pytest.mark.parametrize("key", [Qt.Key.Key_Tab, Qt.Key.Key_Return])
def test_fresh_label_table_keyboard_entry(key: Qt.Key) -> None:
    """Keep successive fresh labels editable without visiting metadata cells."""
    app = QApplication.instance() or QApplication([])
    widget = ConversionChannelsWidget([])
    widget.set_source(3, None)
    widget.show()
    table = widget.table
    table.setCurrentCell(0, 2)
    table.editItem(table.item(0, 2))
    app.processEvents()
    try:
        editor = app.focusWidget()
        assert isinstance(editor, QLineEdit)
        QTest.keyClicks(editor, "GFP")
        QTest.keyClick(editor, key)
        app.processEvents()
        assert widget.value() == ["GFP", "", ""]
        assert table.currentRow() == 1
        assert isinstance(app.focusWidget(), QLineEdit)
        QTest.keyClick(app.focusWidget(), Qt.Key.Key_Escape)
        app.processEvents()
        QTest.keyClick(table, key)
        app.processEvents()
        assert table.currentRow() == 2
        assert table.currentColumn() == 2
        assert isinstance(app.focusWidget(), QLineEdit)
    finally:
        widget.close()
        app.processEvents()


def test_dynamic_table_preserves_blanks_and_user_overrides(tmp_path: Path) -> None:
    """
    Show stored colors while keeping editable labels blank and persisted separately.
    """
    app = QApplication.instance() or QApplication([])
    adapter = SettingsAdapter()
    adapter.raw_channel_count = 3
    adapter.raw_channel_colors = ["#00ff00", "#00ff00", None]
    editor = StepSettingsEditor(adapter, StepName.CONVERT)
    editor.set_expected_channel_counts({3})
    widget = editor.widgets["channel_labels"]
    assert isinstance(widget, ConversionChannelsWidget)
    table = widget.table
    assert table.rowCount() == 3
    assert [cast(QTableWidgetItem, table.horizontalHeaderItem(index)).text() for index in range(3)] == [
        "Channel", "Expected color", "Label"]
    assert [cast(QTableWidgetItem, table.item(index, 2)).text() for index in range(3)] == ["", "", ""]
    assert [cast(QTableWidgetItem, table.item(index, 1)).text() for index in range(3)] == ["green", "green", "nan"]
    assert not cast(QTableWidgetItem, table.item(0, 1)).icon().isNull()
    assert not cast(QTableWidgetItem, table.item(0, 1)).flags() & Qt.ItemFlag.ItemIsEditable
    assert adapter.source_channel_labels() == ["green_1", "green_2", "C3"]
    assert adapter.field_value(StepName.CONVERT, "channel_labels") == []
    cast(QTableWidgetItem, table.item(0, 2)).setText("RFP")
    assert adapter.source_channel_labels() == ["RFP", "green", "C3"]
    assert cast(QTableWidgetItem, table.item(0, 1)).text() == "green"
    editor.sync_to_adapter()
    saved = adapter.save(tmp_path / "settings.toml")
    adapter.load(saved)
    assert adapter.field_value(StepName.CONVERT, "channel_labels") == ["RFP", "", ""]
    editor.close()
    app.processEvents()


def test_label_count_conflict_hides_colors_without_discarding_draft() -> None:
    """
    Keep mismatched saved labels available for correction and suppress color guesses.
    """
    app = QApplication.instance() or QApplication([])
    widget = ConversionChannelsWidget(["GFP"])
    widget.set_source(2, ["#00ff00", "#ff0000"])
    assert widget.value() == ["GFP"]
    assert [cast(QTableWidgetItem, widget.table.item(index, 1)).text() for index in range(2)] == ["nan", "nan"]
    cast(QTableWidgetItem, widget.table.item(1, 2)).setText("RFP")
    assert widget.value() == ["GFP", "RFP"]
    assert cast(QTableWidgetItem, widget.table.item(0, 1)).text() == "green"
    widget.set_source(1, ["#0000ff"])
    assert widget.table.rowCount() == 2
    assert widget.value() == ["GFP", "RFP"]
    cast(QTableWidgetItem, widget.table.item(1, 2)).setText("")
    assert widget.value() == ["GFP"]
    assert widget.table.rowCount() == 1
    assert cast(QTableWidgetItem, widget.table.item(0, 1)).text() == "blue"
    widget.close()
    app.processEvents()


@pytest.mark.parametrize("second, expected", [
    (["#00ff00", "#ff0000"], ["#00ff00", "#ff0000"]),
    (["#00ff00", "#0000ff"], ["#00ff00", None]),
    (None, [None, None]),
])
def test_run_color_consensus(second: list[str | None] | None, expected: list[str | None]) -> None:
    """
    Avoid presenting one acquisition's colors as representative of conflicting inputs.
    """
    first_path, second_path = Path("first.nd2"), Path("second.nd2")
    report = RawInputReport({first_path: 2, second_path: 2}, {}, (), channel_colors={
        first_path: ["#00ff00", "#ff0000"], second_path: second})
    assert report.expected_channel_colors == expected
