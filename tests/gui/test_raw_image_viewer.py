"""Raw image loading belongs to the read-only main Image / Mask Viewer."""

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from tifffile import TiffWriter, imwrite

from scope_io import ScopeIO
from scope_io.metadata.imageJ_meta import make_color_lut
from fisch.gui.viewer.tracking import TrackingViewerWindow
from fisch.gui.main_window import FischMainWindow
from fisch.gui.settings import SettingsAdapter
from fisch.interaction import FischImageSession


def test_main_viewer_reads_raw_tiff_planes_and_source_colors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Browse T/C/Z lazily and keep exact source colors through grayscale toggling.
    """
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "acquisition.tiff"
    pixels = np.arange(2 * 3 * 2 * 5 * 7, dtype=np.uint16).reshape(2, 3, 2, 5, 7)
    red = make_color_lut("red")
    red[0, -1] = 254
    imwrite(source, pixels, imagej=True,
            metadata={"axes": "TZCYX", "LUTs": [red, np.zeros((3, 256), dtype=np.uint8)]})

    def forbid_stack(*args: Any, **kwargs: Any) -> None:
        """
        Fail if viewing requests a complete image stack.
        """
        pytest.fail("Viewer attempted to load the full stack")

    monkeypatch.setattr(ScopeIO, "get_array", forbid_stack)
    window = TrackingViewerWindow(tracking_path=source, editing_enabled=False)
    assert window._raw_source
    assert window._tracking_session is None
    assert window.image_viewer.lut_color == "#fe0000"
    assert window.tool_panel.isEnabled()
    assert window.measurement is not None
    assert window.measurement.drawing.isEnabled()
    assert not window.save_display_button.isEnabled()
    window.frame_slider.setValue(1)
    window.z_slider.setValue(2)
    assert window.image_viewer.image_item.image is not None
    np.testing.assert_array_equal(window.image_viewer.image_item.image, pixels[1, 2, 0])
    window.grayscale_lut_button.setChecked(True)
    assert window.image_viewer.lut_color == "gray"
    window.grayscale_lut_button.setChecked(False)
    assert window.image_viewer.lut_color == "#fe0000"
    window.channel_combo.setCurrentIndex(1)
    assert window.image_viewer.lut_color == "#ffffff"
    assert window.image_viewer.image_item.image is not None
    np.testing.assert_array_equal(window.image_viewer.image_item.image, pixels[1, 2, 1])
    converted = tmp_path / "renamed_converted.tif"
    ScopeIO.from_path(source).save_array(pixels, channel_labels=["GFP", "RFP"], output_path=converted)
    window._open_source(converted)
    assert window.image_viewer.lut_color == "green"
    window.channel_combo.setCurrentIndex(1)
    assert window.image_viewer.lut_color == "red"
    window.close()
    app.processEvents()


def test_main_gui_launches_raw_image_and_switches_series(tmp_path: Path) -> None:
    """
    Route the selected raw file to the main viewer and independently navigate its series.
    """
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "raw.tif"
    with TiffWriter(source) as tif:
        tif.write(np.full((2, 5, 7), 11, dtype=np.uint16), photometric="minisblack", metadata={"axes": "CYX"})
        tif.write(np.full((2, 6, 8), 22, dtype=np.uint16), photometric="minisblack", metadata={"axes": "CYX"})
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    main = FischMainWindow(adapter)
    main._open_selected_report(source)
    viewer = main._tracking_viewer
    assert isinstance(viewer, TrackingViewerWindow)
    assert viewer._raw_source
    assert viewer._source_path == source
    assert viewer.series_combo.count() == 2
    viewer.series_combo.setCurrentIndex(1)
    assert viewer._image_session is not None
    assert viewer._image_session.shape == (2, 6, 8)
    assert viewer.image_viewer.image_item.image is not None
    np.testing.assert_array_equal(viewer.image_viewer.image_item.image, np.full((6, 8), 22))
    main.close()
    app.processEvents()


def test_raw_inputs_are_not_accepted_by_editing_sessions(tmp_path: Path) -> None:
    """
    Keep normalized-artifact validation in the common session and tracking editor.
    """
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "acquisition.tif"
    imwrite(source, np.ones((5, 7), dtype=np.uint16), imagej=True, metadata={"axes": "YX"})
    with pytest.raises(ValueError, match="only accept"):
        FischImageSession(source)
    editor = TrackingViewerWindow(tracking_path=source, editing_enabled=True)
    assert editor._image_session is None
    assert not editor._raw_source
    editor.close()
    app.processEvents()
