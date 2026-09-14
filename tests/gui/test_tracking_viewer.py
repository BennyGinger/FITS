from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_TRACK, StepName
from fits.gui.settings_adapter import SettingsAdapter
from fits.gui.viewer.tracking_window import TrackingViewerWindow
from fits.gui.window import FitsMainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_tracking_viewer_loads_tracks_and_optional_raw_image(
    tmp_path: Path, monkeypatch,
) -> None:
    _app()
    image_path = tmp_path / FITS_ARRAY_NAME
    track_path = tmp_path / FITS_MASK_TRACK
    image_path.touch()
    track_path.touch()
    image = np.arange(2 * 2 * 8 * 8, dtype=np.uint16).reshape(2, 2, 8, 8)
    tracks = np.zeros((2, 2, 8, 8), dtype=np.uint16)
    tracks[:, 0, 2:5, 3:6] = 7
    tracks[:, 1, 1:3, 1:3] = 11
    saves = []
    class Payload:
        def __init__(self, custom_metadata):
            self.custom_metadata = custom_metadata
            self.axes = None
        def with_fitsio(self, *, axes):
            self.axes = axes
            return self
    def save_tracking(array, **kwargs):
        saves.append((array, kwargs))
        return kwargs["output_path"]
    def build_payload(**kwargs):
        return Payload(kwargs["custom_metadata"])
    readers = {
        image_path: SimpleNamespace(
            channel_labels=("GFP", "DAPI"),
            get_array=lambda: SimpleNamespace(array=image, axes="TCYX")),
        track_path: SimpleNamespace(
            channel_labels=("GFP", "RFP"),
            get_array=lambda: SimpleNamespace(array=tracks, axes="TCYX"),
            build_payload=build_payload,
            save_array=save_tracking),
    }
    monkeypatch.setattr(
        "fits.sessions.image.FitsIO.from_path", lambda path: readers[Path(path)])
    monkeypatch.setattr(
        "fits.sessions.tracking.FitsIO.from_path", lambda path: readers[Path(path)])

    window = TrackingViewerWindow(tracking_path=track_path)

    assert window._source_path == track_path
    assert window.frame_slider.maximum() == 1
    assert window.overlay_label.text() == "Mask overlay"
    assert window.raw_image_toggle.text() == "Display raw image"
    assert window.channel_combo.currentText() == "GFP"
    assert window.mask_channel_combo.currentText() == "GFP"
    assert window.image_viewer.mask_item.image[3, 4, 3] == 255
    assert window.show_track_paths.isChecked()
    assert len(window._track_path_items) == 1
    centroids = window._tracking_session.track_centroids("GFP", 0)
    assert window._tracking_session.track_centroids("GFP", 0) is centroids
    np.testing.assert_allclose(centroids[7][0], (0, 4, 3))
    x_values, _ = window._track_path_items[0].getData()
    assert len(x_values) == 1
    window.frame_slider.setValue(1)
    x_values, _ = window._track_path_items[0].getData()
    assert len(x_values) == 2
    assert window.display_label_edit.placeholderText() == "Optional"
    assert window.save_display_button.text() == "Save current display"
    assert window.save_display_button.isEnabled()
    window.channel_combo.setCurrentText("DAPI")
    window.mask_channel_combo.setCurrentText("RFP")
    assert window.channel_combo.currentText() == "DAPI"
    assert window.mask_channel_combo.currentText() == "RFP"
    assert window.image_viewer.mask_item.image[1, 1, 3] == 255
    assert len(window._track_path_items) == 1
    window.raw_image_toggle.setChecked(False)
    assert not window.image_viewer.image_item.isVisible()
    assert window.image_viewer.mask_item.isVisible()
    window.raw_image_toggle.setChecked(True)
    window.display_label_edit.setText("review")
    window.path_thickness.setValue(3)
    window.save_display_button.click()
    saved_array, options = saves[0]
    assert options["output_path"] == tmp_path / "fits_track_review.tif"
    assert saved_array.shape == (*tracks.shape, 3)
    assert saved_array.dtype == np.uint8
    assert np.unique(saved_array.reshape(-1, 3), axis=0).shape[0] > 2
    np.testing.assert_array_equal(saved_array[0, 0, 0, 7], (0, 0, 0))
    assert options["metadata"].axes == "TCYXS"
    metadata = options["metadata"].custom_metadata["tracking_viewer_display"]
    assert metadata["label"] == "review"
    assert metadata["mask_channel"] == "RFP"
    assert metadata["path_thickness_px"] == 3
    assert metadata["output_mode"] == "rgb_rendering"
    assert metadata["raw_image_visible"] is True
    assert metadata["raw_image_exported"] is False
    window.close()


def test_main_window_tracking_button_and_double_click_launch(
    tmp_path: Path, monkeypatch,
) -> None:
    _app()
    track_path = tmp_path / "experiment" / FITS_MASK_TRACK
    track_path.parent.mkdir()
    track_path.touch()
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_field_value(StepName.CONVERT, "channel_labels", ["GFP"])
    window = FitsMainWindow(adapter)
    launched: list[Path] = []
    monkeypatch.setattr(window, "_open_tracking_viewer", launched.append)

    assert window.tracking_viewer_button.isEnabled()
    window._open_selected_report(track_path)
    assert launched == [track_path]
    window.close()
