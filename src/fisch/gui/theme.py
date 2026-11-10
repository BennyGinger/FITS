from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


STEP_TAB_BAR_STYLE = (
    "QTabBar::tab { font-size: 12px; font-weight: normal; padding: 5px 16px; "
    "color: #bfc5cc; background: #292929; border: 1px solid #626262; "
    "border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 5px; }"
    "QTabBar::tab:selected { color: #a8dcff; background: #383838; "
    "border-color: #82b4d6; border-bottom-color: #383838; }"
    "QTabBar::tab:hover:!selected { background: #323232; }")


PREVIEW_BUTTON_STYLE = (
    "QPushButton { background-color: #d97706; color: white; font-weight: bold; "
    "padding: 6px 12px; border-radius: 4px; } "
    "QPushButton:hover { background-color: #ea8a0c; } "
    "QPushButton:pressed, QPushButton:checked { background-color: #b85f05; } "
    "QPushButton:disabled { background-color: #6b4b2a; color: #aaa; }")


def get_application(arguments: Sequence[str] = ()) -> QApplication:
    """
    Reuse the GUI application or create it with the supplied Qt arguments.
    """
    application = QApplication.instance()
    return application if isinstance(application, QApplication) else QApplication(list(arguments))


def apply_dark_theme(app: QApplication) -> None:
    """
    Apply a charcoal Fusion theme with explicit text and indicator contrast.
    """

    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#303030",
        QPalette.ColorRole.WindowText: "#eeeeee",
        QPalette.ColorRole.Base: "#252525",
        QPalette.ColorRole.AlternateBase: "#363636",
        QPalette.ColorRole.Text: "#eeeeee",
        QPalette.ColorRole.PlaceholderText: "#aaaaaa",
        QPalette.ColorRole.Button: "#3c3c3c",
        QPalette.ColorRole.ButtonText: "#eeeeee",
        QPalette.ColorRole.ToolTipBase: "#3c3c3c",
        QPalette.ColorRole.ToolTipText: "#eeeeee",
        QPalette.ColorRole.BrightText: "#ff7070",
        QPalette.ColorRole.Highlight: "#2a82da",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Accent: "#2a82da",
        QPalette.ColorRole.Link: "#79c6ff",
        QPalette.ColorRole.LinkVisited: "#c0a4eb",
        QPalette.ColorRole.Light: "#707070",
        QPalette.ColorRole.Midlight: "#585858",
        QPalette.ColorRole.Mid: "#494949",
        QPalette.ColorRole.Dark: "#202020",
        QPalette.ColorRole.Shadow: "#151515",
    }
    # Setting a role without a group covers active, inactive and disabled windows.
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#9b9b9b"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.PlaceholderText, QColor("#a0a0a0"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor("#526475"))
    app.setPalette(palette)

    icons = Path(__file__).with_name("icons")
    check = (icons / "checkbox-check.svg").as_posix()
    mixed = (icons / "checkbox-mixed.svg").as_posix()
    indicators = "QCheckBox::indicator, QGroupBox::indicator, QAbstractItemView::indicator"

    def states(state: str) -> str:
        """
        Return the current states.
        """
        return ", ".join(f"{selector}{state}" for selector in indicators.split(", "))

    app.setStyleSheet(
        "QToolTip { color: #eeeeee; background-color: #3c3c3c; "
        "border: 1px solid #777; padding: 4px; }"
        f"{indicators} {{ width: 14px; height: 14px; border-radius: 3px; "
        "border: 1px solid #9a9a9a; background: #252525; }"
        f"{states(':checked')}, {states(':indeterminate')} {{ "
        "background: #2a82da; border-color: #84c3ff; }"
        f"{states(':checked')} {{ image: url(\"{check}\"); }}"
        f"{states(':indeterminate')} {{ image: url(\"{mixed}\"); }}"
        f"{states(':hover')}, {states(':focus')} {{ border-color: #c0e6ff; }}"
        f"{states(':pressed')} {{ background: #1d65ac; }}"
        f"{states(':disabled')} {{ border-color: #858585; background: #383838; }}"
        f"{states(':checked:disabled')}, {states(':indeterminate:disabled')} {{ background: #526475; }}"
    )
