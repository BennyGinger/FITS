"""Manual profile ranges, per-axis reset controls and plot navigation."""

import os
from collections.abc import Iterator
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QWidget

from fits.gui.viewer.common.profile_plot import AxisRangeDialog, ProfilePlot


_APP: QApplication | None = None


@pytest.fixture
def plot() -> Iterator[ProfilePlot]:
    """
    Open a real profile canvas with simple, known curve bounds.
    """
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    widget = ProfilePlot()
    widget.resize(760, 400)
    widget.plot(np.arange(11), np.arange(11) * 2 + 10)
    widget.show()
    QApplication.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    QApplication.processEvents()


def test_axis_double_click_edits_range_and_independent_resets_preserve_other_axis(plot: ProfilePlot,
                                                                                monkeypatch: pytest.MonkeyPatch,
                                                                                ) -> None:
    """
    Exercise actual axis double-clicks and preserve manual bounds during curve updates.
    """
    edited: list[str] = []

    def accept_range(dialog: AxisRangeDialog) -> int:
        """
        Supply deterministic limits to the real modal range controls.
        """
        axis = dialog.windowTitle()[0]
        edited.append(axis)
        lower, upper = (2, 5) if axis == "X" else (-20, 100)
        dialog.minimum.setValue(lower)
        dialog.maximum.setValue(upper)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AxisRangeDialog, "exec", accept_range)
    viewport = cast(QWidget, plot.viewport())
    for axis in (plot.x_axis, plot.y_axis):
        point = cast(QPoint, plot.mapFromScene(axis.mapToScene(axis.boundingRect().center())))
        QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QApplication.processEvents()
    assert edited == ["X", "Y"]
    view = plot.getViewBox()
    np.testing.assert_allclose(view.viewRange(), [[2, 5], [-20, 100]])
    plot.clear()
    plot.plot(np.arange(11), np.arange(11) * 3)
    QApplication.processEvents()
    np.testing.assert_allclose(view.viewRange(), [[2, 5], [-20, 100]])
    plot.reset_y_button.click()
    np.testing.assert_allclose(view.viewRange()[0], [2, 5])
    assert view.autoRangeEnabled()[1]
    assert not view.autoRangeEnabled()[0]
    view.setYRange(-3, 3, padding=0)
    plot.reset_x_button.click()
    np.testing.assert_allclose(view.viewRange()[1], [-3, 3])
    assert view.autoRangeEnabled()[0]
    plot.home_button.click()
    assert all(view.autoRangeEnabled())
    ranges = view.viewRange()
    assert ranges[0][0] <= 0 and ranges[0][1] >= 10
    assert ranges[1][0] <= 0 and ranges[1][1] >= 30


def test_range_dialog_requires_increasing_limits_and_cancel_preserves_view(plot: ProfilePlot,
                                                                         monkeypatch: pytest.MonkeyPatch,
                                                                         ) -> None:
    """
    Reject reversed intervals and preserve the graph if editing is cancelled.
    """
    dialog = AxisRangeDialog("x", (1, 5), cast(QWidget, plot))
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok is not None and ok.isEnabled()
    dialog.minimum.setValue(6)
    assert not ok.isEnabled()
    dialog.maximum.setValue(8)
    assert ok.isEnabled()
    before = plot.getViewBox().viewRange()
    monkeypatch.setattr(AxisRangeDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    plot.edit_axis("x")
    np.testing.assert_allclose(plot.getViewBox().viewRange(), before)
    dialog.close()


def test_reset_buttons_follow_axis_ends_after_resizing(plot: ProfilePlot) -> None:
    """
    Keep Home separate from Y reset and align X reset with the horizontal axis.
    """
    for width, height in [(760, 400), (1000, 600)]:
        plot.resize(width, height)
        QApplication.processEvents()
        bounds = plot.getViewBox().sceneBoundingRect()
        top = plot.mapFromScene(bounds.topLeft())
        bottom = plot.mapFromScene(bounds.bottomRight())
        assert abs(plot.reset_y_button.geometry().center().x() - top.x()) <= 2
        assert abs(plot.reset_x_button.geometry().center().y() - bottom.y()) <= 2
        assert plot.reset_x_button.x() > bottom.x()
        assert not plot.home_button.geometry().intersects(plot.reset_y_button.geometry())
        viewport = cast(QWidget, plot.viewport())
        assert viewport.rect().contains(plot.reset_x_button.geometry())
