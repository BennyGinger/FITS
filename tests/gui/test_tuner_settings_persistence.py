"""Tuner edits stay in the GUI draft until explicit saving or pipeline launch."""

from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from time import monotonic
from typing import Any

import numpy as np
import pytest
import tifffile
from PySide6.QtTest import QTest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from fits.environment.constant import StepName
from fits.gui.main_window.window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.gui.settings.field_widgets import ChannelChoiceWidget
from fits.gui.theme import get_application
from fits.gui.segmentation_models.loader import model_options_loader
from fits.gui.viewer.segmentation import SegmentationTunerWindow
from fits.gui.viewer.registration import RegistrationTunerWindow
from fits.gui.viewer.background import BackgroundTunerWindow
from fits.pipeline import start_pipeline
from fits.settings.loader import load_settings, resolve_step_params, run_settings_path
from fits.tasks.registration.tuned import Mode
from fits.tasks.registration.tuning import RegistrationTuningSession
from fits.settings.models import RegisterTimeSettings
from fits.workflows.experiments import discover_saved_states


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FitsMainWindow]:
    """
    Prepare a small converted movie with two channels and an existing settings file.
    """
    app = get_application()
    loader = model_options_loader()
    loader.start()
    loader.wait()
    monkeypatch.setattr(SegmentationTunerWindow, '_initialize_selected_model', lambda self: None)
    monkeypatch.setattr(SegmentationTunerWindow, '_run_preview_when_ready', lambda self: None)
    source = tmp_path / 'source.tif'
    tifffile.imwrite(source, np.zeros((3, 2, 8, 8), dtype=np.uint16),
                     imagej=True, metadata={'axes': 'TCYX'})
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = 'Test'
    adapter.set_runtime_value('execution', 'batch')
    adapter.set_field_value(StepName.CONVERT, 'channel_labels', ['GFP', 'RFP'])
    adapter.set_segment_channels([{'channel': 'GFP', 'do_denoise': False, 'user_settings': {'diameter': 19}}])
    start_pipeline(adapter.save_to_run_dir(), terminal_progress=False)
    main = FitsMainWindow(adapter)
    app.processEvents()
    main._sync_identity()
    yield main
    monkeypatch.setattr('fits.gui.viewer.registration.window.confirm_discard_tuner_changes', lambda parent, tabs: True)
    monkeypatch.setattr('fits.gui.viewer.background.window.confirm_discard_tuner_changes', lambda parent, tabs: True)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Discard)
    if main._registration_tuner is not None:
        main._registration_tuner.close()
    if main._background_tuner is not None:
        main._background_tuner.close()
    if main._segmentation_tuner is not None:
        main._segmentation_tuner.close()
    main.close()
    main.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('mode', ['time', 'channel'])
@pytest.mark.parametrize('action', ['save', 'run', 'run_after_edit'])
def test_tuner_draft_is_persisted_by_main_gui(window: FitsMainWindow,
                                            tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch,
                                            mode: Mode,
                                            action: str,
                                            ) -> None:
    """
    Transfer tuner settings to the GUI and persist the latest choice before worker execution.
    """
    step = StepName.REGISTER_TIME if mode == 'time' else StepName.REGISTER_CHANNEL
    field = 'fit_channel' if mode == 'time' else 'reference_channel'
    settings_path = run_settings_path(tmp_path)
    before = settings_path.read_bytes()
    window._open_registration_tuner(mode)
    tuner = window._registration_tuner
    assert tuner is not None and tuner._session is not None
    tuner.panels[mode].channel.setCurrentText('RFP')
    tuner._save_settings()
    assert window.adapter.field_value(step, field) == 'RFP'
    widget = window._editors[step].widgets[field]
    assert isinstance(widget, ChannelChoiceWidget)
    assert widget.value() == 'RFP'
    assert settings_path.read_bytes() == before
    assert tuner.close()

    expected = 'RFP'
    if action == 'run_after_edit':
        widget.setCurrentIndex(widget.findData('GFP'))
        expected = 'GFP'
    if action == 'save':
        assert window._save_settings() == settings_path
    else:
        captured: list[str] = []

        def run(settings_path: Path, **options: Any) -> None:
            """
            Inspect the published configuration from inside the real pipeline worker.
            """
            captured.append(load_settings(settings_path)[step]['params'][field])

        monkeypatch.setattr('fits.gui.main_window.pipeline_worker.start_pipeline', run)
        window._editors[step].enable_group.setChecked(True)
        window._run_pipeline()
        assert window._thread is not None
        deadline = monotonic() + 10
        while window._thread is not None and monotonic() < deadline:
            QApplication.processEvents()
            QTest.qWait(5)
        assert window._thread is None
        assert captured == [expected]
    assert load_settings(settings_path)[step]['params'][field] == expected


@pytest.mark.parametrize('tool', ['background', 'segmentation', 'compartments'])
@pytest.mark.parametrize('action', ['save', 'run'])
def test_other_tuners_only_update_main_gui_draft(window: FitsMainWindow,
                                                tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch,
                                                tool: str,
                                                action: str,
                                                ) -> None:
    """
    Keep every embedded tuner's run settings on disk unchanged until Save or Run.
    """
    path = run_settings_path(tmp_path)
    before = path.read_bytes()
    if tool == 'background':
        step, field, expected = StepName.BG_SUB, 'sigma', 0.7
        window._open_background_tuner()
        tuner = window._background_tuner
        assert tuner is not None
        tuner.settings_panel.sigma.setValue(expected)
        tuner._save_settings()
        assert window._editors[step].widgets[field].value() == expected
    else:
        window._open_segmentation_tuner('compartment' if tool == 'compartments' else 'segmentation')
        tuner = window._segmentation_tuner
        assert isinstance(tuner, SegmentationTunerWindow)
        if tool == 'compartments':
            step, field, expected = StepName.EXTRACT, 'membrane_thickness', 3.5
            tuner.compartment_panel.thickness.setValue(expected)
        else:
            step, field, expected = StepName.SEGMENT, 'channels', 37
            tuner.settings_panel.diameter.setValue(expected)
        tuner._apply_settings()
        editor = window._editors[step]
        if tool == 'segmentation':
            assert editor.channel_widgets[0]['user_settings.diameter'].value() == expected
        else:
            assert editor.widgets[field].value() == expected
    assert path.read_bytes() == before
    assert tuner.close()

    def value(config: dict[str, Any]) -> Any:
        """
        Read the tuned field from the configuration passed to processing.
        """
        params = resolve_step_params(step, config[step])
        return params['channels'][0]['user_settings']['diameter'] if tool == 'segmentation' else params[field]

    if action == 'save':
        assert window._save_settings() == path
    else:
        captured: list[Any] = []

        def run(settings_path: Path, **options: Any) -> None:
            """
            Confirm settings are published before the pipeline worker starts processing.
            """
            captured.append(value(load_settings(settings_path)))

        monkeypatch.setattr('fits.gui.main_window.pipeline_worker.start_pipeline', run)
        if tool == 'compartments':
            window._editors[StepName.SEGMENT].enable_group.setChecked(True)
        window._editors[step].enable_group.setChecked(True)
        window._run_pipeline()
        assert window._thread is not None
        deadline = monotonic() + 10
        while window._thread is not None and monotonic() < deadline:
            QApplication.processEvents()
            QTest.qWait(5)
        assert window._thread is None
        assert captured == [expected]
    assert value(load_settings(path)) == expected


@pytest.mark.parametrize('tool', ['time', 'channel', 'background', 'segmentation', 'compartments'])
@pytest.mark.parametrize('applied', [False, True])
def test_closing_discards_private_tuner_copy(window: FitsMainWindow,
                                            tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch,
                                            tool: str,
                                            applied: bool,
                                            ) -> None:
    """
    Warn about pending edits, then discard the private copy without changing the main draft.
    """
    before = window.adapter.as_mapping()
    disk = run_settings_path(tmp_path).read_bytes()
    if tool in ('time', 'channel'):
        window._open_registration_tuner(tool)
        tuner = window._registration_tuner
        attribute = '_registration_tuner'
        assert tuner is not None
        tuner.panels[tool].channel.setCurrentText('RFP')
        target = 'fits.gui.viewer.registration.window.confirm_discard_tuner_changes'
    elif tool == 'background':
        window._open_background_tuner()
        tuner = window._background_tuner
        attribute = '_background_tuner'
        assert tuner is not None
        tuner.settings_panel.sigma.setValue(0.7)
        target = 'fits.gui.viewer.background.window.confirm_discard_tuner_changes'
    else:
        window._open_segmentation_tuner('compartment' if tool == 'compartments' else 'segmentation')
        tuner = window._segmentation_tuner
        attribute = '_segmentation_tuner'
        assert isinstance(tuner, SegmentationTunerWindow)
        if tool == 'compartments':
            tuner.compartment_panel.thickness.setValue(3.5)
        else:
            tuner.settings_panel.diameter.setValue(37)
        target = ''
    if applied:
        if isinstance(tuner, RegistrationTunerWindow):
            tuner._save_settings()
            before = window.adapter.as_mapping()
            tuner.panels[tuner.mode()].channel.setCurrentText('GFP')
        elif isinstance(tuner, BackgroundTunerWindow):
            tuner._save_settings()
            before = window.adapter.as_mapping()
            tuner.settings_panel.sigma.setValue(0.8)
        else:
            assert isinstance(tuner, SegmentationTunerWindow)
            tuner._apply_settings()
            before = window.adapter.as_mapping()
            if tool == 'compartments':
                tuner.compartment_panel.thickness.setValue(4.5)
            else:
                tuner.settings_panel.diameter.setValue(41)
    assert window.adapter.as_mapping() == before
    if target:
        monkeypatch.setattr(target, lambda parent, tabs: False)
    else:
        monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Cancel)
    assert not tuner.close()
    assert window.adapter.as_mapping() == before
    if target:
        monkeypatch.setattr(target, lambda parent, tabs: True)
    else:
        monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Discard)
    assert tuner.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert getattr(window, attribute) is None
    assert window.adapter.as_mapping() == before
    assert run_settings_path(tmp_path).read_bytes() == disk


@pytest.mark.parametrize('save', [False, True])
def test_segmentation_channel_deletion_only_merges_on_save(window: FitsMainWindow,
                                                          tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch,
                                                          save: bool,
                                                          ) -> None:
    """
    Apply channel deletions with the private segmentation copy or discard them on close.
    """
    channels = window.adapter.segment_channels()
    window.adapter.set_segment_channels([*channels, {**channels[0], 'channel': 'RFP'}])
    window._populate_from_adapter()
    window._sync_identity()
    before = window.adapter.as_mapping()
    disk = run_settings_path(tmp_path).read_bytes()
    window._open_segmentation_tuner()
    tuner = window._segmentation_tuner
    assert isinstance(tuner, SegmentationTunerWindow)
    tuner._remove_entry(0)
    assert window.adapter.as_mapping() == before
    assert tuner._has_unsaved_settings()
    if save:
        tuner._apply_settings()
        assert [entry['channel'] for entry in window.adapter.segment_channels()] == ['RFP']
        assert not tuner._has_unsaved_settings()
    else:
        monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Discard)
    assert tuner.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert window._segmentation_tuner is None
    if not save:
        assert window.adapter.as_mapping() == before
    assert run_settings_path(tmp_path).read_bytes() == disk


def test_standalone_registration_reads_settings_instead_of_old_cache(window: FitsMainWindow, tmp_path: Path) -> None:
    """
    Build the standalone draft from the settings file even when older tuning exists.
    """
    source = discover_saved_states(tmp_path)[0].artifact('image_raw')
    assert source is not None
    with closing(RegistrationTuningSession(source)) as session:
        session.save_settings(RegisterTimeSettings(fit_channel='RFP'))
    widget = window._editors[StepName.REGISTER_TIME].widgets['fit_channel']
    assert isinstance(widget, ChannelChoiceWidget)
    widget.setCurrentIndex(widget.findData('GFP'))
    assert window._save_settings() is not None
    before = run_settings_path(tmp_path).read_bytes()
    tuner = RegistrationTunerWindow(tmp_path)
    try:
        settings = tuner.current_settings()
        assert isinstance(settings, RegisterTimeSettings)
        assert settings.fit_channel == 'GFP'
    finally:
        tuner.close()
    assert run_settings_path(tmp_path).read_bytes() == before
