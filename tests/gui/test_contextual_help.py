"""Guide navigation, default tabs and shared shortcut filtering."""

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from fisch.gui.help.dialog import HelpDialog
from fisch.gui.help.guide import GuideWidget

_APP: QApplication | None = None


def _app() -> QApplication:
    """
    Retain Qt while help windows are exercised without a display server.
    """
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    return _APP


@pytest.mark.parametrize("gui,default_tab", [("Main", 0), ("Manage files", 0), ("SegTune", 1), ("Tracking", 1)])
def test_context_selects_default_tab_and_collapses_other_shortcuts(gui: str, default_tab: int) -> None:
    """
    Prefer shortcuts only when the caller has them and preserve access to the catalog.
    """
    _app()
    dialog = HelpDialog(title="test", gui=gui, editing_enabled=False, selection_enabled=True)
    try:
        assert dialog.tabs.currentIndex() == default_tab
        assert dialog.other_table.isHidden()
        assert not dialog.other_toggle.isChecked()
        dialog.other_toggle.setChecked(True)
        assert not dialog.other_table.isHidden()
        assert dialog.other_table.rowCount() > 0
        dialog.search.setText("no matching shortcut")
        assert all(dialog.other_table.isRowHidden(row) for row in range(dialog.other_table.rowCount()))
        if gui == "Tracking":
            actions = [dialog.table.item(row, 1) for row in range(dialog.table.rowCount())]
            assert any(item is not None and item.text() == "Select cells in rectangle" for item in actions)
    finally:
        dialog.close()


def test_markdown_links_headings_history_and_find_work_offline() -> None:
    """
    Navigate real Markdown pages, including heading fragments and browser history.
    """
    app = _app()
    guide = GuideWidget("tools/tracking_editor.md#editing-and-saving-tracking-results")
    guide.resize(900, 500)
    guide.show()
    app.processEvents()
    try:
        browser = guide.browser
        assert "Tracking editor" in browser.toPlainText()
        assert browser.verticalScrollBar().value() > 0
        block = browser.document().begin()
        anchors: set[str] = set()
        while block.isValid():
            anchors.update(block.begin().fragment().charFormat().anchorNames())
            block = block.next()
        assert "editing-and-saving-tracking-results" in anchors
        guide.open_page("channels_and_labels.md#rename-channels-in-an-existing-run")
        assert browser.source().fileName() == "channels_and_labels.md"
        guide.back_button.click()
        assert browser.source().fileName() == "tracking_editor.md"
        assert browser.source().fragment() == "editing-and-saving-tracking-results"
        guide.forward_button.click()
        assert browser.source().fileName() == "channels_and_labels.md"
        guide.home_button.click()
        assert browser.source().fileName() == "README.md"
        target = browser.source().resolved(QUrl("settings/tracking.md"))
        browser.setSource(target)
        assert browser.source().fileName() == "tracking.md"
        guide.search.setText("mask repair")
        guide._find_next()
        assert browser.textCursor().selectedText().casefold() == "mask repair"
        assert Path(browser.source().toLocalFile()).is_file()
    finally:
        guide.close()


def test_guide_search_ranks_exact_titles_then_title_words_before_body() -> None:
    """
    Prefer the named topic over another page that only mentions it in its text.
    """
    from fisch.gui.help.search import GuidePage, search_guide

    pages = [GuidePage(Path('segmentation.md'), 'Segmentation', 'tracking is the next step'),
             GuidePage(Path('editor.md'), 'Tracking editor', 'repair cells'),
             GuidePage(Path('tracking.md'), 'Tracking', 'link cells')]
    assert [page.title for page in search_guide(pages, 'TRACKING')] == ['Tracking', 'Tracking editor', 'Segmentation']
    assert search_guide(pages, '   ') == []
    assert search_guide(pages, 'no matching topic') == []


def test_enter_in_search_opens_tracking_settings_before_mentions_elsewhere() -> None:
    """
    Search the real guide and open the highest-ranked standalone settings page.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _app()
    guide = GuideWidget()
    try:
        guide.search.setText('tracking')
        assert guide.browser.source().fileName() == 'README.md'
        first = guide.results.item(0)
        assert first is not None
        assert first.data(Qt.ItemDataRole.UserRole) == 'settings/tracking.md'
        QTest.keyClick(guide.search, Qt.Key.Key_Return)
        assert guide.browser.source().toLocalFile().endswith('/settings/tracking.md')
        assert guide.results.isHidden()
        assert guide.search.text() == 'tracking'
        guide._find_next()
        assert guide.browser.textCursor().selectedText().casefold() == 'tracking'
    finally:
        guide.close()
