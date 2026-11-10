"""Verify asynchronous model discovery without importing Cellpose or loading weights."""

from collections.abc import Iterator
from threading import Event, get_ident
from time import monotonic, sleep
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from fisch.environment.constant import StepName
from fisch.gui.main_window.window import FischMainWindow
from fisch.gui.segmentation_models.loader import ModelOptionsLoader
from fisch.gui.segmentation_models.options import CellposeModelOptions
from fisch.gui.settings import SettingsAdapter, StepSettingsEditor
from fisch.gui.settings.field_widgets import ChoiceWidget, IntWidget


OPTIONS = CellposeModelOptions('v3', 'cyto2', ('cyto2', 'cyto3', 'nuclei'))
_APP: QApplication | None = None


@pytest.fixture
def delayed_loader(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[QApplication, ModelOptionsLoader, Event, list[int]]]:
    """
    Hold discovery in a real worker while allowing settings interactions to proceed.
    """
    global _APP
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    _APP = app
    release = Event()
    calls: list[int] = []

    def discover() -> CellposeModelOptions:
        """
        Return choices only after the test has exercised the pending state.
        """
        calls.append(get_ident())
        if not release.wait(10):
            raise RuntimeError('Test did not release discovery')
        return OPTIONS

    loader = ModelOptionsLoader(app, discover)
    monkeypatch.setattr('fisch.gui.settings.editor.model_options_loader', lambda: loader)
    monkeypatch.setattr('fisch.gui.main_window.window.model_options_loader', lambda: loader)
    monkeypatch.setattr('fisch.gui.settings.editor.model_setting_path', lambda: 'user_settings.model_type')
    try:
        yield app, loader, release, calls
    finally:
        release.set()
        loader.wait()
        app.processEvents()
        loader.deleteLater()
        app.processEvents()


def _finish(app: QApplication, loader: ModelOptionsLoader, release: Event) -> None:
    """
    Deliver the completed worker result through the Qt event loop.
    """
    release.set()
    deadline = monotonic() + 5
    while loader.options is None and not loader.error and monotonic() < deadline:
        app.processEvents()
        sleep(0.005)
    assert loader.options == OPTIONS


def test_discovery_preserves_saved_models_and_user_edits(delayed_loader: tuple[QApplication, ModelOptionsLoader, Event, list[int]]) -> None:
    """
    Keep settings editable while a single background worker discovers additional models.
    """
    app, loader, release, calls = delayed_loader
    adapter = SettingsAdapter()
    adapter.set_segment_channels([{'channel': 'GFP', 'user_settings': {'model_type': 'custom-model', 'diameter': 15}}])
    editor = StepSettingsEditor(adapter, StepName.SEGMENT)
    try:
        model = editor.channel_widgets[0]['user_settings.model_type']
        diameter = editor.channel_widgets[0]['user_settings.diameter']
        assert isinstance(model, ChoiceWidget) and isinstance(diameter, IntWidget)
        assert model.currentText() == 'custom-model'
        assert not calls
        loader.start()
        loader.start()
        diameter.setValue(27)
        _finish(app, loader, release)
        assert len(calls) == 1 and calls[0] != get_ident()
        assert model.currentText() == 'custom-model'
        assert all(model.findText(name) >= 0 for name in OPTIONS.built_in_models)
        assert diameter.value() == 27
        assert adapter.segment_channels()[0]['user_settings']['model_type'] == 'custom-model'
    finally:
        editor.close()
        editor.deleteLater()


def test_empty_model_shows_loading_then_default(delayed_loader: tuple[QApplication, ModelOptionsLoader, Event, list[int]]) -> None:
    """
    Replace a visual loading placeholder with the discovered default rather than saving the placeholder.
    """
    app, loader, release, _ = delayed_loader
    adapter = SettingsAdapter()
    adapter.set_segment_channels([{'channel': 'GFP', 'user_settings': {'model_type': ''}}])
    editor = StepSettingsEditor(adapter, StepName.SEGMENT)
    try:
        model = editor.channel_widgets[0]['user_settings.model_type']
        assert isinstance(model, ChoiceWidget)
        assert model.placeholderText() == 'Loading models…'
        assert model.value() == ''
        loader.start()
        _finish(app, loader, release)
        assert model.value() == 'cyto2'
        assert adapter.segment_channels()[0]['user_settings']['model_type'] == 'cyto2'
    finally:
        editor.close()
        editor.deleteLater()


def test_preview_waits_for_existing_discovery(delayed_loader: tuple[QApplication, ModelOptionsLoader, Event, list[int]], monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Queue one early Preview request and resume it when the shared worker completes.
    """
    app, loader, release, calls = delayed_loader
    window = FischMainWindow()
    try:
        window._open_segmentation_tuner()
        window._open_segmentation_tuner()
        assert window.segtune_button.text() == 'Loading models…'
        resume = Mock()
        monkeypatch.setattr(window, '_open_segmentation_tuner', resume)
        _finish(app, loader, release)
        resume.assert_called_once()
        assert len(calls) == 1
        assert window.segtune_button.text() == 'Preview'
    finally:
        window.close()
        window.deleteLater()


def test_discovery_failure_keeps_saved_settings(delayed_loader: tuple[QApplication, ModelOptionsLoader, Event, list[int]], monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep settings usable and finish the loading state when background imports fail.
    """
    app, _, _, _ = delayed_loader
    failed_loader = ModelOptionsLoader(app, Mock(side_effect=RuntimeError('Backend unavailable')))
    monkeypatch.setattr('fisch.gui.settings.editor.model_options_loader', lambda: failed_loader)
    monkeypatch.setattr('fisch.gui.main_window.window.model_options_loader', lambda: failed_loader)
    warning = Mock()
    monkeypatch.setattr('fisch.gui.main_window.window.QMessageBox.warning', warning)
    adapter = SettingsAdapter()
    adapter.set_segment_channels([{'channel': 'GFP', 'user_settings': {'model_type': 'saved-model'}}])
    window = FischMainWindow(adapter)
    try:
        window._open_segmentation_tuner()
        deadline = monotonic() + 5
        while not failed_loader.error and monotonic() < deadline:
            app.processEvents()
            sleep(0.005)
        assert failed_loader.error == 'Backend unavailable'
        model = window._editors[StepName.SEGMENT].channel_widgets[0]['user_settings.model_type']
        assert isinstance(model, ChoiceWidget) and model.currentText() == 'saved-model'
        assert 'Backend unavailable' in model.toolTip()
        assert window.segtune_button.text() == 'Preview'
        assert adapter.segment_channels()[0]['user_settings']['model_type'] == 'saved-model'
        warning.assert_called_once()
    finally:
        failed_loader.wait()
        window.close()
        window.deleteLater()
        failed_loader.deleteLater()
        app.processEvents()
