from __future__ import annotations
from copy import deepcopy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QPushButton,
)

from fits.environment.constant import StepName
from fits.gui.settings.field_widgets import (
    ChannelSelectionWidget, ExportChannelsWidget, IntWidget, TextWidget,
    ValueWidget, create_field_widget,)
from fits.gui.settings.adapter import (
    RUNTIME_CHOICES,
    SettingsAdapter,
    field_choices,
    field_label,
    field_tooltip,
    runtime_field_tooltip,
)
from fits.gui.settings.layouts import STEP_LAYOUTS

TRACK_POSTPROCESS_PARAMETERS = (
    "postprocess.shape_similarity",
    "postprocess.minimum_appearances",
    "postprocess.extrapolate_start",
    "postprocess.extrapolate_end",
)


class StableAdvancedGroup(QGroupBox):
    """Hide advanced fields while reserving their space in the layout."""

    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.setCheckable(True)
        self.content = QWidget()
        policy = self.content.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.content.setSizePolicy(policy)
        layout = QVBoxLayout(self)
        layout.addWidget(self.content)
        self.form = QFormLayout(self.content)
        self.toggled.connect(self.content.setVisible)
        self.setChecked(False)
        self.content.hide()


class StepSettingsEditor(QWidget):
    """Dynamically render the basic and advanced fields for one workflow step."""

    value_changed = Signal()

    def __init__(
        self,
        adapter: SettingsAdapter,
        step: StepName,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.step = step
        self.widgets: dict[str, ValueWidget] = {}
        self._editable = True

        layout_spec = STEP_LAYOUTS[step]
        self._advanced_paths = set(layout_spec.advanced)
        outer = QVBoxLayout(self)
        self.outer_layout = outer

        title = QLabel(f"<h2>{layout_spec.title}</h2>")
        outer.addWidget(title)

        description = QLabel(adapter.step_description(step))
        description.setWordWrap(True)
        description.setStyleSheet("color: #b8b8b8;")
        description.setToolTip(adapter.step_documentation(step))
        outer.addWidget(description)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        contents_layout = QVBoxLayout(contents)

        basic = QGroupBox("Basic settings")
        basic_form = QFormLayout(basic)
        self._add_fields(basic_form, layout_spec.basic)
        contents_layout.addWidget(basic)
        if step == StepName.SEGMENT:
            self.channel_sections = QWidget()
            self.channel_sections_layout = QVBoxLayout(self.channel_sections)
            contents_layout.addWidget(self.channel_sections)
            self._build_channel_sections()

        advanced = StableAdvancedGroup("Advanced settings")
        self._add_fields(advanced.form, layout_spec.advanced)
        advanced.toggled.connect(self._refresh_enabled_states)
        self._advanced_group = advanced
        contents_layout.addWidget(advanced)
        contents_layout.addStretch()

        scroll.setWidget(contents)
        outer.addWidget(scroll)
        self._refresh_enabled_states()

    def _add_fields(self, form: QFormLayout, paths: tuple[str, ...]) -> None:
        for path in paths:
            value = self.adapter.field_value(self.step, path)
            if self.step == StepName.CONVERT and path == "export_channels":
                widget = ExportChannelsWidget(value)
            elif self.step == StepName.TRACK and path == "channel_to_track":
                channels = self._segmentation_channel_labels()
                selected = [label for label in value if label in channels]
                widget = ChannelSelectionWidget(channels, selected or channels)
                self.adapter.set_field_value(self.step, path, widget.value())
            else:
                widget = create_field_widget(value, field_choices(self.step, path))
            tooltip = field_tooltip(self.step, path)
            widget.setToolTip(tooltip)
            if path in ("expected_ref_masks", "expected_roi_masks") and isinstance(widget, IntWidget):
                widget.setMinimum(1 if path == "expected_ref_masks" else 0)
            widget.value_changed.connect(
                lambda changed_value, field_path=path: self._store_value(
                    field_path, changed_value
                )
            )
            label = QLabel(field_label(path))
            label.setToolTip(tooltip)
            form.addRow(label, widget)
            self.widgets[path] = widget

    def _segmentation_channel_labels(self) -> list[str]:
        return list(dict.fromkeys(
            str(entry.get("channel", "")).strip()
            for entry in self.adapter.segment_channels()
            if str(entry.get("channel", "")).strip()))

    def refresh_tracking_channels(self) -> None:
        """Refresh choices from segmentation, selecting newly added channels."""
        widget = self.widgets.get("channel_to_track")
        if not isinstance(widget, ChannelSelectionWidget):
            return
        previous_options = [widget.item(index).text()
                            for index in range(widget.count())]
        selected = widget.value()
        channels = self._segmentation_channel_labels()
        selected.extend(channel for channel in channels
                        if channel not in previous_options)
        widget.set_channels(channels, selected)
        self.adapter.set_field_value(self.step, "channel_to_track", widget.value())
        self.value_changed.emit()

    def _build_channel_sections(self) -> None:
        self.channel_widgets: list[dict[str, ValueWidget]] = []
        layout = self.channel_sections_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        entries = self.adapter.segment_channels()
        if not entries:
            entries = [{"channel": "", "do_denoise": True, "nuclear_channel": "None",
                        "user_settings": {"model_type": "cyto3", "diameter": 15,
                                          "flow_threshold": 0.4, "cellprob_threshold": 0.0,
                                          "do_3D": False, "stitch_threshold": 0.0}}]
            self.adapter.set_segment_channels(entries)
        for index, entry in enumerate(entries):
            channel_widgets = {}
            self.channel_widgets.append(channel_widgets)
            group = QGroupBox(f"Channel {index + 1}")
            form = QFormLayout(group)
            defaults = {"channel": "", "do_denoise": True, "nuclear_channel": "None",
                        "user_settings.model_type": "cyto3", "user_settings.diameter": 15,
                        "user_settings.flow_threshold": 0.4, "user_settings.cellprob_threshold": 0.0,
                        "user_settings.do_3D": False, "user_settings.stitch_threshold": 0.0}
            for path, default in defaults.items():
                value = entry
                for part in path.split("."):
                    value = value.get(part, default) if isinstance(value, dict) else default
                widget = create_field_widget("None" if value is None else value,
                                             field_choices(self.step, path))
                channel_widgets[path] = widget
                widget.setToolTip(field_tooltip(self.step, path))
                widget.value_changed.connect(
                    lambda value, i=index, p=path: self._store_channel(i, p, value))
                if path == "channel":
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.addWidget(widget)
                    add = QPushButton("+")
                    remove = QPushButton("−")
                    add.setFixedWidth(28)
                    remove.setFixedWidth(28)
                    add.setToolTip("Add another channel settings section")
                    remove.setToolTip("Remove this channel settings section")
                    remove.setEnabled(len(entries) > 1)
                    add.clicked.connect(lambda checked=False, i=index: self._add_channel(i))
                    remove.clicked.connect(lambda checked=False, i=index: self._remove_channel(i))
                    row_layout.addWidget(add)
                    row_layout.addWidget(remove)
                    form.addRow("Channel to segment", row)
                else:
                    form.addRow(field_label(path), widget)
            layout.addWidget(group)
        self.channel_sections.setEnabled(self._editable)

    def _store_channel(self, index: int, path: str, value: object) -> None:
        entries = self.adapter.segment_channels()
        node = entries[index]
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.adapter.set_segment_channels(entries)
        self.value_changed.emit()

    def _add_channel(self, index: int) -> None:
        entries = self.adapter.segment_channels()
        entry = deepcopy(entries[index])
        entry["channel"] = ""
        entries.insert(index + 1, entry)
        self.adapter.set_segment_channels(entries)
        self._build_channel_sections()
        self.value_changed.emit()

    def _remove_channel(self, index: int) -> None:
        entries = self.adapter.segment_channels()
        if len(entries) > 1:
            entries.pop(index)
            self.adapter.set_segment_channels(entries)
            self._build_channel_sections()
            self.value_changed.emit()

    def _store_value(self, path: str, value: object) -> None:
        self.adapter.set_field_value(self.step, path, value)
        self._update_worker_state()
        self._update_mask_request_state()
        self._update_track_postprocess_state()
        self.value_changed.emit()

    def sync_to_adapter(self) -> None:
        for path, widget in self.widgets.items():
            self.adapter.set_field_value(self.step, path, widget.value())
        for index, widgets in enumerate(getattr(self, "channel_widgets", [])):
            for path, widget in widgets.items():
                self._store_channel(index, path, widget.value())

    def _update_worker_state(self) -> None:
        execution = self.widgets.get("execution")
        workers = self.widgets.get("workers")
        if execution is not None and workers is not None:
            is_serial = execution.value() == "serial"
            section_enabled = (
                "workers" not in self._advanced_paths
                or self._advanced_group.isChecked()
            )
            workers.setEnabled(self._editable and section_enabled and not is_serial)
            tooltip = field_tooltip(self.step, "workers")
            if is_serial:
                tooltip = f"{tooltip} Ignored during serial execution."
            workers.setToolTip(tooltip)

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        if hasattr(self, "channel_sections"):
            self.channel_sections.setEnabled(editable)
        self._refresh_enabled_states()

    def _update_mask_request_state(self) -> None:
        for toggle_path, count_path in (
                ("draw_ref_mask", "expected_ref_masks"),
                ("draw_roi_mask", "expected_roi_masks")):
            toggle = self.widgets.get(toggle_path)
            count = self.widgets.get(count_path)
            if count is not None:
                count.setEnabled(self._editable and (toggle is None or toggle.value()))

    def _update_track_postprocess_state(self) -> None:
        toggle = self.widgets.get("postprocess.enabled")
        if toggle is None:
            return
        parameters_enabled = (
            self._editable
            and bool(toggle.value())
        )
        for path in TRACK_POSTPROCESS_PARAMETERS:
            parameter = self.widgets.get(path)
            if parameter is not None:
                parameter.setEnabled(parameters_enabled)

    def _refresh_enabled_states(self) -> None:
        for path, widget in self.widgets.items():
            if path != "workers":
                section_enabled = (
                    path not in self._advanced_paths
                    or self._advanced_group.isChecked()
                )
                widget.setEnabled(self._editable and section_enabled)
        self._update_worker_state()
        self._update_mask_request_state()
        self._update_track_postprocess_state()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._update_worker_state()
        super().showEvent(event)


class RuntimeSettingsEditor(QWidget):
    """Edit the application-level runtime options."""

    value_changed = Signal()

    def __init__(
        self,
        adapter: SettingsAdapter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.widgets: dict[str, ValueWidget] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        group = StableAdvancedGroup("Advanced runtime settings")
        form = group.form
        form.setVerticalSpacing(8)
        for name in (
            "execution", "console_level", "file_level", "log_dir", "unlock_all_tabs"
        ):
            widget = create_field_widget(
                adapter.runtime_value(name),
                RUNTIME_CHOICES.get(name),
            )
            tooltip = runtime_field_tooltip(name)
            widget.setToolTip(tooltip)
            if name == "log_dir" and isinstance(widget, TextWidget):
                widget.setPlaceholderText("Use run_dir/.fits (default)")
            widget.value_changed.connect(
                lambda value, field_name=name: self._store_value(field_name, value))
            label = QLabel(field_label(name))
            label.setToolTip(tooltip)
            form.addRow(label, widget)
            self.widgets[name] = widget
        group.toggled.connect(self._set_fields_enabled)
        group.setMinimumHeight(210)
        self._advanced_group = group
        outer.addWidget(group)
        self._set_fields_enabled(group.isChecked())

    def _store_value(self, name: str, value: object) -> None:
        self.adapter.set_runtime_value(name, value)
        self.value_changed.emit()

    def _set_fields_enabled(self, enabled: bool) -> None:
        for widget in self.widgets.values():
            widget.setEnabled(enabled)

    def sync_to_adapter(self) -> None:
        for name, widget in self.widgets.items():
            self.adapter.set_runtime_value(name, widget.value())
