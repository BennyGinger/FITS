"""Verify browser integration and actionable optional-viewer feedback."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
import pytest

from fits.gui.main_window.window import FitsMainWindow
from fits.gui.parquet import open_parquet
from fits.gui.settings import SettingsAdapter


@pytest.fixture
def application() -> Iterator[QApplication]:
    """
    Keep the Qt application alive for each table-viewer interaction.
    """
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    yield app
    app.processEvents()


def test_browser_activation_launches_tad(application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Open an existing table through the browser signal using its exact file path.
    """
    parquet = tmp_path / 'table with spaces.parquet'
    parquet.touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    launch = Mock()
    monkeypatch.setattr('fits.gui.parquet.launch_tad', launch)
    window = FitsMainWindow(adapter)
    try:
        window.run_browser.path_activated.emit(parquet)
        launch.assert_called_once_with(Path(__file__).resolve().parents[2], parquet)
    finally:
        window.close()
        window.deleteLater()


def test_missing_tad_explains_alternatives(application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Display a clickable installation link and reassure users that FITS remains usable.
    """
    monkeypatch.setattr('fits.gui.parquet.launch_tad', Mock(side_effect=FileNotFoundError('missing')))
    inspected: list[str] = []

    def inspect() -> None:
        """
        Inspect and dismiss the actual missing-viewer message.
        """
        message = application.activeModalWidget()
        assert isinstance(message, QMessageBox)
        try:
            assert message.windowTitle() == 'Tad is not installed'
            assert message.textFormat() == Qt.TextFormat.RichText
            assert 'href="https://www.tadviewer.com/"' in message.text()
            assert 'Data Wrangler' in message.text()
            assert 'FITS remains fully operational' in message.text()
            assert any(label.openExternalLinks() for label in message.findChildren(QLabel))
            inspected.append(message.text())
        finally:
            message.accept()

    QTimer.singleShot(0, inspect)
    open_parquet(tmp_path / 'table.parquet')
    assert inspected


def test_launch_failure_is_reported(application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Report an installed viewer that cannot start without raising into the GUI.
    """
    monkeypatch.setattr('fits.gui.parquet.launch_tad', Mock(side_effect=PermissionError('Permission denied')))
    warning = Mock()
    monkeypatch.setattr(QMessageBox, 'warning', warning)
    open_parquet(tmp_path / 'table.parquet')
    assert warning.call_args.args[1] == 'Cannot open Tad'
    assert 'Permission denied' in warning.call_args.args[2]
