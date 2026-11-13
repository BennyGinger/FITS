"""Offline Markdown navigation using Qt's existing text browser."""

from pathlib import Path
import re

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTextBrowser, QVBoxLayout, QWidget


from fisch.gui.help.search import GuidePage, index_guide, search_guide


def guide_root() -> Path:
    """
    Locate the guide in the checkout used by the installed application.
    """
    return Path(__file__).resolve().parents[4] / "docs" / "user_guide"


class _MarkdownBrowser(QTextBrowser):
    """Give Markdown headings the same fragment names as the linked guide."""

    def doSetSource(self, url: QUrl, type: QTextDocument.ResourceType = QTextDocument.ResourceType.UnknownResource) -> None:
        """
        Load the document and attach heading anchors before fragment navigation.
        """
        super().doSetSource(url, type)
        block = self.document().begin()
        seen: dict[str, int] = {}
        while block.isValid():
            if block.blockFormat().headingLevel():
                slug = re.sub(r"[^\w\- ]", "", block.text().lower()).replace(" ", "-")
                count = seen.get(slug, 0)
                seen[slug] = count + 1
                anchor = f"{slug}-{count}" if count else slug
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                format = QTextCharFormat()
                format.setAnchor(True)
                format.setAnchorNames([anchor])
                cursor.mergeCharFormat(format)
            block = block.next()
        if url.hasFragment():
            self.scrollToAnchor(url.fragment())


class GuideWidget(QWidget):
    """Read the guide with history, title-first page search and in-page finding."""

    def __init__(self, page: str = "README.md", parent: QWidget | None = None) -> None:
        """
        Open a contextual page once without following later application tab changes.
        """
        super().__init__(parent)
        self.root = guide_root()
        self._search_pages: list[GuidePage] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.browser = _MarkdownBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setSearchPaths([str(self.root)])
        self.browser.setStyleSheet("QTextBrowser { padding: 12px; }")
        self.back_button = QPushButton("Back")
        self.forward_button = QPushButton("Forward")
        self.home_button = QPushButton("Home")
        self.back_button.clicked.connect(self.browser.backward)
        self.forward_button.clicked.connect(self.browser.forward)
        self.home_button.clicked.connect(lambda: self.open_page("README.md"))
        self.browser.backwardAvailable.connect(self.back_button.setEnabled)
        self.browser.forwardAvailable.connect(self.forward_button.setEnabled)
        self.back_button.setEnabled(False)
        self.forward_button.setEnabled(False)
        for button in (self.back_button, self.forward_button, self.home_button):
            toolbar.addWidget(button)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the guide…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._update_search_results)
        self.search.returnPressed.connect(self._open_first_result)
        toolbar.addWidget(self.search, 1)
        find = QPushButton("Find in page")
        find.clicked.connect(self._find_next)
        toolbar.addWidget(find)
        layout.addLayout(toolbar)
        self.results = QListWidget()
        self.results.setAccessibleName("Guide search results, title matches first")
        self.results.setMaximumHeight(190)
        self.results.hide()
        self.results.itemClicked.connect(self._open_search_result)
        self.results.itemActivated.connect(self._open_search_result)
        layout.addWidget(self.results)
        layout.addWidget(self.browser, 1)
        self.open_page(page)

    def open_page(self, page: str) -> None:
        """
        Open a guide page, falling back to home when that page is unavailable.
        """
        name, _, fragment = page.partition("#")
        path = self.root / name
        if not path.is_file() and name != "README.md":
            path = self.root / "README.md"
            fragment = ""
        if not path.is_file():
            self.browser.setPlainText(f"The user guide could not be found at {path}.\nOpen FIScH from its installed checkout to read the bundled documentation.")
            return
        url = QUrl.fromLocalFile(str(path))
        url.setFragment(fragment)
        self.browser.setSource(url)

    def _update_search_results(self, query: str) -> None:
        """
        List matching pages with title matches first, without navigating while typing.
        """
        self.results.clear()
        if not query.strip():
            self.results.hide()
            return
        if self._search_pages is None:
            self._search_pages = index_guide(self.root)
        for page in search_guide(self._search_pages, query):
            category = page.path.parent.name if page.path.parent != Path('.') else "overview / reference"
            item = QListWidgetItem(f"{page.title} — {category}")
            item.setData(Qt.ItemDataRole.UserRole, page.path.as_posix())
            item.setToolTip(page.path.as_posix())
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        else:
            item = QListWidgetItem("No matching pages")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(item)
        self.results.show()

    def _open_first_result(self) -> None:
        """
        Open the highest-ranked result when Enter is pressed in guide search.
        """
        item = self.results.currentItem()
        if item is not None:
            self._open_search_result(item)

    def _open_search_result(self, item: QListWidgetItem) -> None:
        """
        Open a selected result while retaining the query for Find in page.
        """
        page = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(page, str):
            self.open_page(page)
            self.results.hide()

    def _find_next(self) -> None:
        """
        Find text, wrapping to the beginning when needed.
        """
        text = self.search.text()
        if text and not self.browser.find(text):
            self.browser.moveCursor(QTextCursor.MoveOperation.Start)
            self.browser.find(text)
