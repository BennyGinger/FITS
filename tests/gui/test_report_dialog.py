"""Long reports fit the screen and remain readable in a resizable window."""
import os
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTabWidget, QWidget

from fits.gui.run_result.report import ReportDialog
from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.workflows.runtime.progress.outcome import RunResult

_APP = None


def application():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_long_report_fits_small_screen_and_can_resize_and_scroll(monkeypatch):
    app = application()
    screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 800, 600))
    monkeypatch.setattr(ReportDialog, 'screen', lambda self: screen)
    lines = ['FITS pipeline report', 'Created: today',
             'Experiments: 100 completed / 0 partial / 0 skipped / 0 failed',
             'Experiment details', '------------------']
    lines += [f'Experiment {index}: ' + 'long diagnostic message ' * 30 for index in range(300)]
    content = '\n'.join(lines)
    dialog = ReportDialog(Path('fits_report_' + 'x' * 200 + '.txt'), content)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.width() <= 800 and dialog.height() <= 600
        assert dialog.isSizeGripEnabled()
        assert dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
        dialog.resize(480, 340)
        app.processEvents()
        assert dialog.size().width() == 480 and dialog.size().height() == 340
        assert dialog.details.verticalScrollBar().maximum() > 0
        tabs = dialog.findChild(QTabWidget)
        assert tabs is not None
        tabs.setCurrentIndex(1)
        app.processEvents()
        original = tabs.widget(1)
        assert isinstance(original, QPlainTextEdit)
        assert original.toPlainText() == content
        assert original.verticalScrollBar().maximum() > 0
        assert original.horizontalScrollBar().maximum() > 0
    finally:
        dialog.close()


def test_pipeline_error_uses_scrollable_report_instead_of_message_box(monkeypatch: pytest.MonkeyPatch) -> None:
    application()
    window = FitsMainWindow(SettingsAdapter())
    captured = {}
    def completion(result: RunResult, root: Path, parent: QWidget, **kwargs: object) -> None:
        """
        Capture the shared failure report after worker cleanup.
        """
        captured['result'] = result
    monkeypatch.setattr('fits.gui.main_window.window.show_run_result', completion)
    try:
        message = 'Rebuild conflicts\n' + 'file.tif\n' * 1000
        window._pipeline_failed(message, 'Full traceback')
        window._thread_finished()
        assert not captured['result'].successful
        assert message in captured['result'].report
        assert 'Full traceback' in captured['result'].report
    finally:
        window.close()
