"""Readable placeholder and checkbox rendering with the application theme."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QStyle, QStyleOptionButton

from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.gui.theme import apply_dark_theme

_APP = None


@pytest.fixture
def themed_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    old_style = _APP.style().objectName() or "Fusion"
    old_palette = QPalette(_APP.palette())
    old_stylesheet = _APP.styleSheet()
    apply_dark_theme(_APP)
    yield _APP
    _APP.setStyle(old_style)
    _APP.setPalette(old_palette)
    _APP.setStyleSheet(old_stylesheet)


def contrast(first: QColor, second: QColor) -> float:
    def luminance(color):
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("group", [QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                                    QPalette.ColorGroup.Disabled])
def test_main_window_inherits_readable_text_and_placeholder_colors(themed_app, group):
    window = FitsMainWindow(SettingsAdapter())
    try:
        field = window.run_dir_edit
        assert field.placeholderText()
        palette = field.palette()
        background = palette.color(group, QPalette.ColorRole.Base)
        placeholder = palette.color(group, QPalette.ColorRole.PlaceholderText)
        text = palette.color(group, QPalette.ColorRole.Text)
        assert placeholder.alpha() == 255
        assert contrast(placeholder, background) >= 4.5
        assert contrast(text, background) >= 4.5
        assert background == themed_app.palette().color(group, QPalette.ColorRole.Base)
        assert window.centralWidget().palette().color(group, QPalette.ColorRole.Window) == (
            themed_app.palette().color(group, QPalette.ColorRole.Window))
    finally:
        window.close()
        window.deleteLater()
        themed_app.processEvents()


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("state", [Qt.CheckState.Unchecked, Qt.CheckState.Checked,
                                   Qt.CheckState.PartiallyChecked])
def test_rendered_checkbox_outline_and_marks_remain_visible(themed_app, enabled, state):
    checkbox = QCheckBox("Target channel")
    checkbox.setCheckState(state)
    checkbox.setEnabled(enabled)
    checkbox.resize(180, 32)
    checkbox.show()
    themed_app.processEvents()
    option = QStyleOptionButton()
    checkbox.initStyleOption(option)
    rect = checkbox.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox)
    image = checkbox.grab().toImage().scaled(checkbox.size()).copy(rect)
    try:
        assert not image.isNull()
        if state == Qt.CheckState.Unchecked:
            border = image.pixelColor(0, image.height() // 2)
            fill = image.pixelColor(image.width() // 2, image.height() // 2)
            assert contrast(border, fill) >= 3
        else:
            # The bundled tick/mixed mark must actually render, including disabled.
            bright = sum(image.pixelColor(x, y).lightness() > 210
                         for y in range(2, image.height() - 2)
                         for x in range(2, image.width() - 2))
            assert bright >= 4
    finally:
        checkbox.close()
        checkbox.deleteLater()
        themed_app.processEvents()
