from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFileDialog,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from fits.environment.constant import FITS_ARRAY_NAME
from fits.gui.run_browser import DirectoryBrowser
from fits.gui.viewer.image_viewer import FitsImageViewer
from fits.gui.wheel_widgets import FocusWheelSlider
from fits.sessions.image import FitsImageSession


class ImageToolWindow(QMainWindow):
    """Shared image browsing, display and navigation for focused tools."""

    source_panel_sizes = (230, 750)
    file_filters: tuple[str, ...]
    tool_help: str

    def __init__(self, experiments_dir: str | Path | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.resize(1700, 1150)
        self._image_session: FitsImageSession | None = None
        self._source_path: Path | None = None
        self._displayed_channel: str | None = None
        self._channel_levels: dict[str, tuple[float, float]] = {}
        self._build_ui()
        self._connect_signals()
        self._install_keyboard_shortcuts()
        self._set_source_controls_enabled(False)
        if experiments_dir is not None:
            self._set_experiments_directory(experiments_dir)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(8, 8, 8, 8)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        outer_layout.addWidget(main_splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.left_splitter = left_splitter
        left_splitter.setChildrenCollapsible(False)
        left_splitter.setHandleWidth(8)
        left_splitter.setStyleSheet("QSplitter::handle:vertical { background: #526170; margin: 2px 24px; }")
        left_splitter.addWidget(self._build_source_controls())

        left_splitter.addWidget(self._build_tools())
        left_splitter.handle(1).setToolTip("Drag up or down to resize the experiment list and settings.")
        left_splitter.setStretchFactor(0, 2)
        left_splitter.setStretchFactor(1, 6)
        left_splitter.setSizes(list(self.source_panel_sizes))
        left_layout.addWidget(left_splitter)
        main_splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_layout.addWidget(right_splitter)

        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(0, 0, 0, 0)
        info_row = QHBoxLayout()
        info_row.setContentsMargins(24, 0, 24, 0)
        left_controls = QHBoxLayout()
        left_controls.addWidget(QLabel("Channel"))
        self.channel_combo = QComboBox()
        left_controls.addWidget(self.channel_combo)
        self.grayscale_lut_button = QPushButton("Grayscale")
        self.grayscale_lut_button.setCheckable(True)
        self.grayscale_lut_button.setToolTip(
            "Toggle grayscale display. Turn it off to restore the channel colour.")
        self.grayscale_lut_button.setStyleSheet(
            "QPushButton:checked { background-color: #2a82da; color: white; "
            "border: 1px solid #7fc0ff; }")
        left_controls.addWidget(self.grayscale_lut_button)
        left_controls.addStretch(1)
        info_row.addLayout(left_controls, 1)
        self._build_mode_controls(info_row)

        right_controls = QHBoxLayout()
        right_controls.addStretch(1)
        right_controls.addWidget(QLabel("Overlay"))
        self.show_mask = QCheckBox()
        self.show_mask.setChecked(True)
        self.show_mask.setToolTip("Show or hide the mask overlay.")
        right_controls.addWidget(self.show_mask)
        self.mask_opacity = FocusWheelSlider(Qt.Orientation.Horizontal)
        self.mask_opacity.setRange(0, 100)
        self.mask_opacity.setValue(45)
        self.mask_opacity.setMaximumWidth(140)
        self.mask_opacity.setToolTip("Adjust the opacity of the displayed mask overlay.")
        right_controls.addWidget(self.mask_opacity)
        self._build_overlay_controls(right_controls)
        info_row.addLayout(right_controls, 1)

        self.info_button = QToolButton()
        self.info_button.setText("i")
        self.info_button.setToolTip("Viewer information and keyboard shortcuts")
        self.info_button.setFixedSize(26, 26)
        self.info_button.setStyleSheet(
            "QToolButton { border: 1px solid #888; border-radius: 13px; "
            "font-weight: bold; font-style: italic; }")
        info_row.addWidget(self.info_button)
        image_layout.addLayout(info_row)
        self.image_viewer = FitsImageViewer()
        image_layout.addWidget(self.image_viewer, 1)
        navigation = QHBoxLayout()
        self.frame_slider, self.frame_value = self._navigation_control("Frame", navigation)
        self.z_slider, self.z_value = self._navigation_control("Z", navigation)
        image_layout.addLayout(navigation)
        right_splitter.addWidget(image_panel)

        lut_panel = QWidget()
        footer_layout = QHBoxLayout(lut_panel)
        footer_layout.setContentsMargins(24, 0, 24, 0)
        self.lut_controls = QWidget()
        lut_layout = QHBoxLayout(self.lut_controls)
        lut_layout.setContentsMargins(0, 0, 0, 0)
        self.image_viewer.histogram.setMaximumHeight(125)
        self.image_viewer.histogram.setToolTip(
            "Adjust the displayed intensity range. Add a colour marker from the "
            "gradient menu; click a marker to edit its colour, or remove it from "
            "the colour dialog.")
        lut_layout.addWidget(self.image_viewer.histogram, 1)
        lut_actions = QVBoxLayout()
        lut_actions.addStretch(1)
        self.auto_scale_button = QPushButton("Auto-scale")
        lut_actions.addWidget(self.auto_scale_button)
        self.full_range_button = QPushButton("Full range")
        lut_actions.addWidget(self.full_range_button)
        lut_actions.addStretch(1)
        lut_layout.addLayout(lut_actions)
        footer_layout.addWidget(self.lut_controls, 1)
        self.viewer_actions = QWidget()
        action_layout = QHBoxLayout(self.viewer_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self._build_viewer_actions(action_layout)
        footer_layout.addWidget(self.viewer_actions, 1)
        right_splitter.addWidget(lut_panel)
        right_splitter.setStretchFactor(0, 7)
        right_splitter.setStretchFactor(1, 1)
        right_splitter.setSizes([875, 125])
        main_splitter.addWidget(right)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes([500, 1050])

        self.status_bar = QWidget()
        self.status_bar.setFixedHeight(28)
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("Choose an experiments directory, then select a FITS experiment.")
        status_layout.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.hide()
        status_layout.addWidget(self.progress)
        outer_layout.addWidget(self.status_bar)

    def _build_source_controls(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        directory_row = QHBoxLayout()
        directory_row.addWidget(QLabel("Experiments directory"))
        self.directory_edit = QLineEdit()
        self.directory_edit.setPlaceholderText("Choose a directory containing experiments")
        directory_row.addWidget(self.directory_edit, 1)
        self.browse_button = QPushButton("Browse")
        directory_row.addWidget(self.browse_button)
        layout.addLayout(directory_row)

        self.directory_browser = DirectoryBrowser(
            "Experiments directory contents", file_name_filters=self.file_filters)
        layout.addWidget(self.directory_browser)
        return container

    def _connect_source_controls(self) -> None:
        self.browse_button.clicked.connect(self._browse)
        self.directory_edit.returnPressed.connect(
            lambda: self._set_experiments_directory(self.directory_edit.text()))
        self.directory_browser.path_selected.connect(self._path_selected)

    def _connect_signals(self) -> None:
        self._connect_source_controls()
        self.frame_slider.valueChanged.connect(self._display_selection)
        self.channel_combo.currentIndexChanged.connect(self._display_selection)
        self.z_slider.valueChanged.connect(self._display_selection)
        self._connect_tools()
        self.grayscale_lut_button.toggled.connect(
            lambda checked: self.image_viewer.set_coloured_lut(not checked))
        self.auto_scale_button.clicked.connect(self.image_viewer.auto_scale)
        self.full_range_button.clicked.connect(self.image_viewer.full_range)
        self.info_button.clicked.connect(self._show_information)
        self.show_mask.toggled.connect(self.image_viewer.set_mask_visible)
        self.mask_opacity.valueChanged.connect(
            lambda value: self.image_viewer.set_mask_opacity(value / 100.0))

    @Slot()
    def _show_information(self) -> None:
        text = (
            "Browse normalized FITS experiments and adjust image contrast.\n\n"
            "Keyboard shortcuts\n"
            "X    Toggle mask overlay\n"
            "← / → or A / D    Previous / next frame\n"
            "↑ / ↓    Previous / next Z plane\n"
            "W / Z    Next / previous Z plane\n"
            "C    Next channel\n"
            "Ctrl + mouse drag    Pan image\n"
            "Ctrl + mouse wheel    Zoom image\n"
            + self.tool_help + f"\nFITS {self._package_version('fits')}")
        QMessageBox.information(self, f"About {self.windowTitle()}", text)

    @staticmethod
    def _package_version(distribution: str) -> str:
        try:
            return version(distribution)
        except PackageNotFoundError:
            return "development version"

    def _install_keyboard_shortcuts(self) -> None:
        self.installEventFilter(self)
        central = self.centralWidget()
        central.installEventFilter(self)
        for widget in central.findChildren(QWidget):
            widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() != QEvent.Type.KeyPress
                or not isinstance(event, QKeyEvent)
                or not self.isActiveWindow()):
            return super().eventFilter(watched, event)
        focus = self.focusWidget()
        numeric_editor = self._parent_spin_box(focus)
        key = event.key()
        if isinstance(focus, QLineEdit) and numeric_editor is None:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                QTimer.singleShot(0, self.image_viewer.setFocus)
            return super().eventFilter(watched, event)

        if self._tool_keypress(event):
            return True
        if event.modifiers() not in (Qt.KeyboardModifier.NoModifier,
                                     Qt.KeyboardModifier.ShiftModifier):
            return super().eventFilter(watched, event)
        if numeric_editor is not None and key in (
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,):
            return super().eventFilter(watched, event)
        if key == Qt.Key.Key_X:
            if self._image_session is not None:
                self.show_mask.toggle()
            return True
        if key in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self._step_slider(self.frame_slider, 1)
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self._step_slider(self.frame_slider, -1)
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_W):
            self._step_slider(self.z_slider, 1)
            return True
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Z):
            self._step_slider(self.z_slider, -1)
            return True
        if key == Qt.Key.Key_C:
            self._next_channel()
            return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _parent_spin_box(widget: QWidget | None) -> QAbstractSpinBox | None:
        while widget is not None:
            if isinstance(widget, QAbstractSpinBox):
                return widget
            widget = widget.parentWidget()
        return None

    @staticmethod
    def _step_slider(slider: QSlider, step: int) -> None:
        if slider.isEnabled():
            slider.setValue(slider.value() + step)

    def _next_channel(self) -> None:
        if self.channel_combo.isEnabled() and self.channel_combo.count() > 0:
            next_index = (self.channel_combo.currentIndex() + 1) % self.channel_combo.count()
            self.channel_combo.setCurrentIndex(next_index)

    @staticmethod
    def _navigation_control(label: str,
                            layout: QHBoxLayout,
                            ) -> tuple[QSlider, QLabel]:
        layout.addWidget(QLabel(label))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 0)
        layout.addWidget(slider, 1)
        value = QLabel("1 / 1")
        value.setMinimumWidth(60)
        layout.addWidget(value)
        return slider, value

    @Slot()
    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose experiments directory",
            self.directory_edit.text(),)
        if selected:
            self._set_experiments_directory(selected)

    def _set_experiments_directory(self, path: str | Path) -> None:
        raw_path = str(path).strip()
        resolved = Path(raw_path).expanduser().resolve() if raw_path else None
        if resolved is None or not resolved.is_dir():
            self.directory_edit.setText(raw_path)
            self.directory_browser.set_root("")
            self._close_session()
            self.status_label.setText("Choose an existing experiments directory.")
            return
        self.directory_edit.setText(str(resolved))
        self.status_label.setText("Select an experiment folder or its fits_array.tif file.")
        self.directory_browser.set_root(resolved)

    @Slot()
    def _display_selection(self) -> None:
        if self._image_session is None or self.channel_combo.currentIndex() < 0:
            return
        frame = self.frame_slider.value()
        z_index = self.z_slider.value()
        channel = self.channel_combo.currentText()
        try:
            if self._displayed_channel is not None and self._displayed_channel != channel:
                self._channel_levels[self._displayed_channel] = self.image_viewer.display_levels
            self.image_viewer.set_channel_lut(channel)
            image = self._image_session.display_frame(frame, channel, z_index)
            self.image_viewer.set_image(image)
            if self._displayed_channel != channel:
                if channel in self._channel_levels:
                    self.image_viewer.set_display_levels(self._channel_levels[channel])
                else:
                    self.image_viewer.auto_scale()
                    self._channel_levels[channel] = self.image_viewer.display_levels
            self._displayed_channel = channel
            self.image_viewer.clear_mask()
            self._display_overlay(image, frame, channel, z_index)
            self.image_viewer.set_mask_visible(self.show_mask.isChecked())
            self.image_viewer.set_mask_opacity(self.mask_opacity.value() / 100.0)
        except Exception as error:
            self.status_label.setText(str(error))
            return
        self.frame_value.setText(
            f"{frame + 1} / {self._image_session.frame_count}")
        self.z_value.setText(
            f"{z_index + 1} / {self._image_session.plane_count}")

    def _set_source_controls_enabled(self, enabled: bool) -> None:
        self.tool_panel.setEnabled(enabled)
        self.frame_slider.setEnabled(enabled)
        self.channel_combo.setEnabled(enabled)
        self.z_slider.setEnabled(enabled)

    def _close_session(self) -> None:
        self._clear_tools()
        self._image_session = None
        self._source_path = None
        self._displayed_channel = None
        self._channel_levels.clear()
        self.image_viewer.image_item.clear()
        self.image_viewer.clear_mask()
        self.image_viewer.set_drawing_enabled(False)
        self.channel_combo.clear()
        self.frame_slider.setRange(0, 0)
        self.z_slider.setRange(0, 0)
        self.frame_value.setText("1 / 1")
        self.z_value.setText("1 / 1")
        self._set_source_controls_enabled(False)

    def _build_tools(self) -> QWidget:
        raise NotImplementedError

    def _build_mode_controls(self, layout: QHBoxLayout) -> None:
        """Optional compact mode indicator above the image."""

    def _build_viewer_actions(self, layout: QHBoxLayout) -> None:
        """Optional session actions beside the half-width LUT controls."""

    def _build_overlay_controls(self, layout: QHBoxLayout) -> None:
        raise NotImplementedError

    def _connect_tools(self) -> None:
        raise NotImplementedError

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        raise NotImplementedError

    def _display_overlay(self, image, frame, channel, z_index) -> None:
        raise NotImplementedError

    def _clear_tools(self) -> None:
        raise NotImplementedError

    def _path_selected(self, selected: object) -> None:
        raise NotImplementedError

    def closeEvent(self, event: QCloseEvent) -> None:
        self._close_session()
        super().closeEvent(event)
