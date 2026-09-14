import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QPushButton

from fits.environment.constant import StepName
from fits.gui.settings_adapter import SettingsAdapter
from fits.gui.settings_editor import StepSettingsEditor
from fits.gui.viewer.segmentation_window import SegmentationTunerWindow
from fits.gui.viewer.tools.segmentation.worker import ModelInitializationRequest, ModelInitializationWorker
from fits.settings.models import SegmentChannelSettings

_APP = None


def application():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_channel_sections_add_edit_remove_and_round_trip(tmp_path):
    application()
    adapter = SettingsAdapter()
    adapter.set_segment_channels([{"channel": "GFP", "user_settings": {"diameter": 20}}])
    editor = StepSettingsEditor(adapter, StepName.SEGMENT)
    editor._add_channel(0)
    editor.channel_widgets[1]["channel"].setText("DAPI")
    editor.channel_widgets[1]["user_settings.diameter"].setValue(12)
    editor.sync_to_adapter()
    assert adapter.segment_channels()[0]["user_settings"]["diameter"] == 20
    assert adapter.segment_channels()[1]["user_settings"]["diameter"] == 12
    destination = adapter.save(tmp_path / "settings.toml")
    loaded = SettingsAdapter()
    loaded.load(destination)
    assert [entry.channel for entry in loaded.segmentation_settings().channels] == ["GFP", "DAPI"]
    editor._remove_channel(0)
    assert adapter.segmentation_settings().channels[0].channel == "DAPI"
    editor._remove_channel(0)
    assert len(adapter.segment_channels()) == 1
    editor.close()


def test_tuner_switches_independent_channels_and_applies_collection(monkeypatch, tmp_path):
    application()

    class Session:
        channel_labels = ("GFP", "DAPI", "RFP")
        frame_count = 1
        plane_count = 1
        axes = "CYX"
        shape = (3, 8, 8)

        def __init__(self, source):
            self.segment_settings = SegmentChannelSettings(channel="GFP")

        def set_segment_settings(self, settings):
            self.segment_settings = settings

        def display_frame(self, *args):
            return np.zeros((8, 8))

        def load_cached_preview(self, *args):
            return None

        def close(self):
            pass

    monkeypatch.setattr("fits.gui.viewer.segmentation_window.SegmentationTuningSession", Session)
    monkeypatch.setattr(SegmentationTunerWindow, "_initialize_selected_model", lambda self: None)
    source = tmp_path / "fits_array.tif"
    source.touch()
    window = SegmentationTunerWindow()
    window._open_source(source)
    assert window.channel_combo.currentText() == "GFP"
    assert len(window._entries) == 1
    bins = lambda: [button for button in window.channel_settings_list.findChildren(QPushButton)
                    if button.toolTip().startswith("Remove settings")]
    assert not bins()[0].isEnabled()
    window.settings_panel.diameter.setValue(35)
    assert window.diameter_reference.rect().width() == 35
    window._add_channel()
    assert window.channel_combo.currentText() == "DAPI"
    assert window.channel_combo.findText("GFP") == -1
    window.settings_panel.diameter.setValue(12)
    window.settings_panel.denoise.setChecked(False)
    window._select_entry(0)
    assert window.settings_panel.diameter.value() == 35
    window._select_entry(1)
    assert window.settings_panel.diameter.value() == 12
    assert window.diameter_reference.rect().width() == 12
    assert not window.settings_panel.denoise.isChecked()
    window._remove_entry(0)
    assert window.channel_combo.currentText() == "DAPI"
    assert window.channel_combo.findText("GFP") >= 0
    assert len(window._entries) == 1
    window._add_channel()
    assert window.channel_combo.currentText() == "GFP"
    emitted = []
    window.settings_applied.connect(emitted.append)
    window._apply_settings()
    assert [entry.channel for entry in emitted[0].channels] == ["DAPI", "GFP"]
    assert emitted[0].channels[0].user_settings["diameter"] == 12


def test_tuner_initialization_reuses_both_models(monkeypatch):
    application()
    initialized = []

    class Backend:
        model_names = ["cyto2", "cyto3"]

        def configure_model(self, settings, do_denoise):
            return {"model_type": settings["model_type"]}

        def supported_settings(self, do_denoise):
            return {"model_type", "diameter"}

        def init_model(self, settings, do_denoise):
            initialized.append(settings["model_type"])
            return object()

        def configure_eval_params(self, settings, use_nuclear_channel, do_denoise):
            return {"diameter": settings.get("diameter", 20)}

    monkeypatch.setattr("cellpose_kit.workflow.configuration.load_backend", lambda: (Backend(), "v3"))
    monkeypatch.setattr("cellpose_kit.client._models", {})
    failures = []
    for model in ("cyto2", "cyto3", "cyto2", "cyto3"):
        request = ModelInitializationRequest(SegmentChannelSettings(
            channel="GFP", user_settings={"model_type": model}))
        worker = ModelInitializationWorker(request)
        worker.failed.connect(lambda request, message: failures.append(message))
        worker.run()
    assert failures == []
    assert initialized == ["cyto2", "cyto3"]


def test_diameter_reference_has_image_pixel_size_and_follows_visible_corner():
    from fits.gui.viewer.image_viewer import FitsImageViewer
    from fits.gui.viewer.tools.segmentation.diameter_reference import DiameterReference

    application()
    viewer = FitsImageViewer()
    image = np.zeros((256, 256))
    viewer.set_image(image)
    reference = DiameterReference(viewer.view_box, viewer.image_item)
    reference.set_diameter(30)
    assert reference.isVisible()
    assert reference.rect().width() == reference.rect().height() == 30
    viewer.view_box.setRange(xRange=(64, 164), yRange=(64, 164), padding=0)
    visible = viewer.view_box.viewRect().intersected(viewer.image_item.boundingRect())
    assert reference.pos().x() >= visible.left()
    assert reference.pos().y() + 30 < visible.bottom()
    assert reference.rect().width() == 30
    np.testing.assert_array_equal(viewer.image_item.image, image)
    reference.set_diameter(0)
    assert not reference.isVisible()
    viewer.close()
