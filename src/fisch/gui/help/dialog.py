"""One help window for contextual documentation and searchable shortcuts."""

from collections.abc import Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from fisch.gui.help.guide import GuideWidget
from fisch.gui.help.shortcuts import HelpRow, VIEWER_HELP, local_shortcuts, relevant_shortcuts


def info_button(parent: QWidget | None = None) -> QToolButton:
    """
    Build the same compact information button in every interface.
    """
    button = QToolButton(parent)
    button.setText("i")
    button.setAccessibleName("User guide and shortcuts")
    button.setToolTip("User guide and keyboard shortcuts")
    button.setFixedSize(26, 26)
    button.setStyleSheet("QToolButton { border: 1px solid #aaaaaa; border-radius: 13px; font-weight: bold; font-size: 16px; }")
    return button


def _shortcut_table(rows: Sequence[HelpRow], show_gui: bool) -> QTableWidget:
    """
    Render catalog entries using the same columns in both table sections.
    """
    table = QTableWidget(len(rows), 4)
    table.setHorizontalHeaderLabels(["Shortcut", "Function", "GUI", "Mode / condition"])
    table.setColumnHidden(2, not show_gui)
    table.verticalHeader().hide()
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setWordWrap(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    for index, row in enumerate(rows):
        for column, value in enumerate(row):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(index, column, item)
    return table


class HelpDialog(QDialog):
    """Keep documentation and shortcut help in one independently navigable window."""

    def __init__(self, parent: QWidget | None = None, *, title: str, version: str = "",
                 gui: str | None = None, rows: Sequence[HelpRow] = VIEWER_HELP,
                 editing_enabled: bool = True, selection_enabled: bool = False,
                 guide_page: str = "README.md",
                 ) -> None:
        """
        Choose the initial guide page and default tab from the opening context.
        """
        super().__init__(parent)
        self.setWindowTitle(f"{title} — Help")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1050, 700)
        relevant = relevant_shortcuts(rows, gui, editing_enabled, selection_enabled)
        others = [row for row in dict.fromkeys(VIEWER_HELP) if row not in relevant]
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.guide = GuideWidget(guide_page)
        self.tabs.addTab(self.guide, "User guide")
        shortcuts = QWidget()
        controls = QVBoxLayout(shortcuts)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a shortcut, function, or mode…")
        self.search.setClearButtonEnabled(True)
        controls.addWidget(self.search)
        if not relevant:
            controls.addWidget(QLabel("No shortcuts are defined for this interface. Other tools' shortcuts are available below."))
        self.table = _shortcut_table(local_shortcuts(relevant, gui, editing_enabled), show_gui=gui is None)
        self.table.setVisible(bool(relevant))
        controls.addWidget(self.table, 1)
        self.other_toggle = QToolButton()
        self.other_toggle.setText("Other shortcuts")
        self.other_toggle.setCheckable(True)
        self.other_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.other_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.other_toggle.setVisible(bool(others))
        controls.addWidget(self.other_toggle)
        self.other_table = _shortcut_table(others, show_gui=True)
        self.other_table.hide()
        controls.addWidget(self.other_table, 1)
        self.other_toggle.toggled.connect(self._toggle_other)
        self.search.textChanged.connect(self._filter)
        self.tabs.addTab(shortcuts, "Shortcuts")
        self.tabs.setCurrentIndex(1 if relevant else 0)
        self.tabs.currentChanged.connect(lambda _index: QTimer.singleShot(0, self._fit_tables))
        layout.addWidget(self.tabs, 1)
        if version:
            layout.addWidget(QLabel(f"FIScH {version}"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_other(self, expanded: bool) -> None:
        """
        Reveal other tools' shortcuts without changing the local table.
        """
        self.other_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.other_table.setVisible(expanded)
        self._fit_tables()

    def _filter(self, text: str) -> None:
        """
        Search visible and collapsed shortcut sections using the same query.
        """
        query = text.strip().casefold()
        for table in (self.table, self.other_table):
            for row in range(table.rowCount()):
                values = [item.text() for column in range(table.columnCount())
                          if (item := table.item(row, column)) is not None]
                table.setRowHidden(row, query not in " ".join(values).casefold())

    def _fit_tables(self) -> None:
        """
        Fit wrapped shortcut columns to the available window width.
        """
        for table in (self.table, self.other_table):
            width = table.viewport().width()
            table.setColumnWidth(0, int(width * 0.26))
            if not table.isColumnHidden(2):
                table.setColumnWidth(2, int(width * 0.16))
            table.setColumnWidth(3, int(width * 0.31))
            table.resizeRowsToContents()

    def showEvent(self, event: QShowEvent) -> None:
        """
        Keep the help window within the current screen's available area.
        """
        super().showEvent(event)
        available = self.screen().availableGeometry()
        self.resize(min(self.width(), available.width() - 40), min(self.height(), available.height() - 60))
        self._fit_tables()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """
        Rewrap shortcut descriptions after resizing.
        """
        super().resizeEvent(event)
        if hasattr(self, "table"):
            self._fit_tables()


def show_help(parent: QWidget, *, title: str, gui: str, guide_page: str,
              editing_enabled: bool = True, selection_enabled: bool = False,
              ) -> HelpDialog:
    """
    Open a modeless help window with a snapshot of the caller's current context.
    """
    for previous in parent.findChildren(HelpDialog, "fischHelpWindow", Qt.FindChildOption.FindDirectChildrenOnly):
        previous.close()
    dialog = HelpDialog(parent, title=title, gui=gui, guide_page=guide_page,
                        editing_enabled=editing_enabled, selection_enabled=selection_enabled)
    dialog.setObjectName("fischHelpWindow")
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()
    return dialog
