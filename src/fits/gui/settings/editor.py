from __future__ import annotations

from PySide6.QtGui import QFont, QShowEvent
from copy import deepcopy
from typing import Any, cast
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QHBoxLayout, QPushButton
from fits.environment.constant import RegistrationContext, StepName
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.gui.settings.field_widgets import BoolWidget, ChannelChoiceWidget, ChoiceWidget, ChannelSelectionWidget, ExportChannelsWidget, FloatWidget, IntWidget, TextWidget, ValueWidget, create_field_widget
from fits.gui.settings.adapter import RUNTIME_CHOICES, SettingsAdapter, field_choices, field_hint, field_label, field_tooltip, runtime_field_tooltip
from fits.gui.settings.layouts import STEP_LAYOUTS
from fits.gui.settings.conversion_channels import ConversionChannelsWidget
from fits.gui.segmentation_models.loader import model_options_loader
from fits.gui.segmentation_models.options import CellposeModelOptions, model_setting_path


TRACK_POSTPROCESS_PARAMETERS = (
    "postprocess.shape_similarity",
    "postprocess.minimum_appearances",
    "postprocess.extrapolate_start",
    "postprocess.extrapolate_end",
)

COMPARTMENT_PARAMETERS = ("compartments", "membrane_thickness", "dilation_radius", "save_compartment_masks")
WORKFLOW_INCLUSION_TOOLTIP = (
    "Checked: use this step's output, reusing existing results when valid.\n"
    "Unchecked: bypass this step and ignore its saved output when selecting downstream inputs.")


def _add_parameter_row(form: QFormLayout,
                       title: str,
                       widget: QWidget,
                       tooltip: str,
                       label_width: int,
                       hint: str | None = None,
                       trailing: QWidget | None = None,
                       ) -> QWidget:
    """
    Place a compact parameter and a practical hint in balanced left/right columns.
    """
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(24)
    controls = QWidget()
    controls_form = QFormLayout(controls)
    controls_form.setContentsMargins(0, 0, 0, 0)
    controls_form.setHorizontalSpacing(18)
    controls_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
    widget.setToolTip(tooltip)
    if isinstance(widget, (IntWidget, FloatWidget)):
        widget.setFixedWidth(110)
    elif not isinstance(widget, ConversionChannelsWidget):
        widget.setMaximumWidth(220)
    field = widget
    if trailing is not None:
        field = QWidget()
        field_layout = QHBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.addWidget(widget)
        field_layout.addWidget(trailing)
    if title:
        label = QLabel(title)
        label.setFixedWidth(label_width)
        label.setWordWrap(True)
        label.setToolTip(tooltip)
        controls_form.addRow(label, field)
    else:
        controls_form.addRow(field)
    layout.addWidget(controls, 1)
    description = QLabel(hint or tooltip.split(". ", 1)[0].rstrip(".") + ".")
    description.setWordWrap(True)
    description.setToolTip(tooltip)
    description.setStyleSheet("color: #a0a0a0; font-size: 11px; font-style: italic;")
    description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    layout.addWidget(description, 1)
    form.addRow(row)
    return row


class CollapsibleAdvancedGroup(QGroupBox):
    """Expand advanced fields only when requested, without reserving space."""

    def __init__(self, title: str) -> None:
        """
        Initialize the CollapsibleAdvancedGroup state and dependencies.
        """
        super().__init__(title)
        self.setCheckable(True)
        self.setFlat(True)
        self.content = QWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.content)
        self.form = QFormLayout(self.content)
        self.toggled.connect(self.content.setVisible)
        self.setChecked(False)
        self.content.hide()


class StepSettingsEditor(QWidget):
    """Dynamically render the basic and advanced fields for one workflow step."""

    value_changed = Signal()
    enabled_changed = Signal(bool)

    def __init__(self, adapter: SettingsAdapter, step: StepName, parent: QWidget | None = None) -> None:
        """
        Initialize the StepSettingsEditor state and dependencies.
        """
        super().__init__(parent)
        self.adapter = adapter
        self.step = step
        self._model_loader = model_options_loader() if step == StepName.SEGMENT else None
        if self._model_loader is not None:
            self._model_loader.ready.connect(self._model_choices_ready)
            self._model_loader.failed.connect(self._model_choices_failed)
        self.widgets: dict[str, ValueWidget | ChannelChoiceWidget | ChannelSelectionWidget] = {}
        self._field_rows: list[QWidget] = []
        self._editable = True
        self._track_postprocess_parameters: QWidget | None = None

        layout_spec = STEP_LAYOUTS[step]
        self._advanced_paths = set(layout_spec.advanced)
        outer = QVBoxLayout(self)
        self.outer_layout = outer

        description = QLabel(adapter.step_description(step))
        description.setWordWrap(True)
        description.setStyleSheet("color: #b8b8b8;")
        description.setToolTip(adapter.step_documentation(step))
        self.description_layout = QHBoxLayout()
        self.description_layout.setSpacing(16)
        self.description_layout.addWidget(description, 1)
        outer.addLayout(self.description_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        contents_layout = QVBoxLayout(contents)

        basic = QGroupBox("Include in workflow")
        basic.setCheckable(True)
        basic.setToolTip(WORKFLOW_INCLUSION_TOOLTIP)
        basic.setChecked(adapter.step_enabled(step))
        self.enable_group = basic
        basic.toggled.connect(self._enabled_toggled)
        basic_form = QFormLayout(basic)
        if step == StepName.TRACK:
            self._add_fields(basic_form, tuple(path for path in layout_spec.basic
                                               if not path.startswith("postprocess.")))
        elif step == StepName.EXTRACT:
            self._add_fields(basic_form, tuple(path for path in layout_spec.basic if path not in COMPARTMENT_PARAMETERS))
        else:
            self._add_fields(basic_form, layout_spec.basic)
        contents_layout.addWidget(basic)
        if step == StepName.EXTRACT:
            self._add_compartment_section(contents_layout)
        if step == StepName.TRACK:
            self._add_track_postprocess_section(contents_layout)
        if step == StepName.SEGMENT:
            self.channel_sections = QWidget()
            self.channel_sections_layout = QVBoxLayout(self.channel_sections)
            contents_layout.addWidget(self.channel_sections)
            self._build_channel_sections()

        advanced = CollapsibleAdvancedGroup("Advanced settings")
        self._add_fields(advanced.form, layout_spec.advanced)
        advanced.toggled.connect(self._refresh_enabled_states)
        self._advanced_group = advanced
        contents_layout.addWidget(advanced)
        contents_layout.addStretch()
        contents_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(contents)
        self.scroll_area = scroll
        outer.addWidget(scroll)
        self._refresh_enabled_states()

    def _add_compartment_section(self, parent_layout: QVBoxLayout) -> None:
        """
        Put the compartment toggle and preview above the settings.
        """
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        toggle = BoolWidget(bool(self.adapter.field_value(self.step, "compartments")))
        toggle.setText(field_label("compartments"))
        toggle.setToolTip(field_tooltip(self.step, "compartments"))
        toggle.value_changed.connect(lambda value: self._store_value("compartments", value))
        self.widgets["compartments"] = cast(ValueWidget, toggle)
        header_layout.addWidget(toggle)
        header_layout.addStretch()
        self.compartment_preview_button = QPushButton("Preview")
        self.compartment_preview_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header_layout.addWidget(self.compartment_preview_button)
        parent_layout.addWidget(header)
        self._field_rows.append(header)

        self.compartment_group = QGroupBox()
        self.compartment_group.setFlat(True)
        self.compartment_group.setAccessibleName(field_label("compartments"))
        compartment_form = QFormLayout(self.compartment_group)
        explanation = QLabel("Measure membrane and cytoplasm separately. Masks are generated during quantification "
                             "and can be regenerated with the same settings. Saving is optional; compaction removes exports.")
        explanation.setWordWrap(True)
        compartment_form.addRow(explanation)
        self._add_fields(compartment_form, tuple(path for path in COMPARTMENT_PARAMETERS if path != "compartments"))
        parent_layout.addWidget(self.compartment_group)

    def _enabled_toggled(self, enabled: bool) -> None:
        """
        Enabled toggled.
        """
        self.adapter.set_step_enabled(self.step, enabled)
        self.set_editable(enabled)
        self.enabled_changed.emit(enabled)
        self.value_changed.emit()

    def _add_fields(self,
                    form: QFormLayout,
                    paths: tuple[str, ...],
                    hints: dict[str, str] | None = None,
                    ) -> None:
        """
        Add fields.
        """
        label_width = max((self.fontMetrics().horizontalAdvance(field_label(path))
                           for path in paths), default=0) + 12
        for path in paths:
            value = self.adapter.field_value(self.step, path)
            if self.step == StepName.CONVERT and path == "channel_labels":
                labels = [value] if isinstance(value, str) else list(value or [])
                widget = ConversionChannelsWidget(labels)
            elif self.step == StepName.CONVERT and path == "export_channels":
                widget = ExportChannelsWidget(value, self.adapter.source_channel_labels() or self.adapter.saved_image_channels)
            elif self.step == StepName.TRACK and path == "channel_to_track":
                channels = self._segmentation_channel_labels()
                selected = [label for label in value if label in channels]
                widget = ChannelSelectionWidget(channels, selected or channels)
                self.adapter.set_field_value(self.step, path, widget.value())
            else:
                widget = self._create_parameter_widget(path, value)
            tooltip = field_tooltip(self.step, path)
            trailing = None
            if self.step == StepName.CONVERT and path == "channel_labels":
                self.expected_channels_label = QLabel()
                font = QFont(self.font())
                font.setItalic(True)
                self.expected_channels_label.setFont(font)
                self.expected_channels_label.hide()
                trailing = self.expected_channels_label
            widget.setToolTip(tooltip)
            if path in ("expected_ref_masks", "expected_roi_masks") and isinstance(widget, IntWidget):
                widget.setMinimum(1 if path == "expected_ref_masks" else 0)
            widget.value_changed.connect(lambda changed_value, field_path=path: self._store_value(field_path,
                                                                                                  changed_value,
                                                                                                  ),
                                         )
            title = "" if isinstance(widget, ConversionChannelsWidget) else field_label(path)
            row = _add_parameter_row(form, title, widget, tooltip, label_width,
                                     hint=hints.get(path, field_hint(self.step, path)) if hints else field_hint(self.step, path),
                                     trailing=trailing,
                                     )
            self._field_rows.append(row)
            self.widgets[path] = widget

    def set_expected_channel_counts(self, counts: set[int], warning: str = "") -> None:
        """
        Update table rows from detected channel counts and show only mismatch warnings.
        """
        text = "Channel label count mismatch" if warning and len(counts) == 1 else ""
        self.expected_channels_label.setText(text)
        color = "#efb366" if text else ""
        self.expected_channels_label.setStyleSheet(f"color: {color};" if color else "")
        self.expected_channels_label.setToolTip(warning)
        self.expected_channels_label.setVisible(bool(text))
        widget = self.widgets.get("channel_labels")
        if isinstance(widget, ConversionChannelsWidget):
            widget.set_source(next(iter(counts)) if len(counts) == 1 else None,
                              self.adapter.raw_channel_colors,
                              )

    def _create_parameter_widget(self, path: str, value: Any) -> ValueWidget | ChannelChoiceWidget | ChannelSelectionWidget:
        """
        Build a parameter control using available channels and meaningful numeric bounds.
        """
        if (self.step, path) in ((StepName.REGISTER_TIME, "fit_channel"),
                                (StepName.REGISTER_CHANNEL, "reference_channel"),
                                (StepName.SEGMENT, "channel"),
                                (StepName.SEGMENT, "nuclear_channel")):
            return ChannelChoiceWidget(self.adapter.exported_channel_labels(), value,
                                       optional=path in ("fit_channel", "nuclear_channel"),
                                       )
        if path == "exclude_channel" and self.step in (StepName.BG_SUB, StepName.REGISTER_CHANNEL):
            selected = self._selected_channel_labels(value)
            return ChannelSelectionWidget(self.adapter.exported_channel_labels(), selected, allow_none=True)
        if ((self.step == StepName.SEGMENT and path == "user_settings.diameter")
                or (self.step == StepName.BG_SUB and path == "size")):
            widget = IntWidget(round(float(value)))
            widget.setMinimum(2 if self.step == StepName.BG_SUB else 0)
            return cast(ValueWidget, widget)
        bounded = (self.step, path) in (
            (StepName.BG_SUB, "threshold"),
            (StepName.TRACK, "postprocess.shape_similarity"),
            (StepName.SEGMENT, "user_settings.stitch_threshold"),
        )
        continuous = bounded or (self.step == StepName.SEGMENT and path in (
            "user_settings.flow_threshold", "user_settings.cellprob_threshold"))
        widget = create_field_widget(float(value) if continuous else value,
                                     field_choices(self.step, path),
                                     )
        if bounded and isinstance(widget, FloatWidget):
            widget.setRange(0, 1)
        if continuous and self.step in (StepName.SEGMENT, StepName.TRACK) and isinstance(widget, FloatWidget):
            widget.setSingleStep(0.1)
        if self.step == StepName.SEGMENT and path == "user_settings.flow_threshold" and isinstance(widget, (IntWidget, FloatWidget)):
            widget.setMinimum(0)
        return widget

    @staticmethod
    def _selected_channel_labels(value: Any) -> list[str]:
        """
        Normalize saved optional channel selections for the GUI.
        """
        if value is None or value == "None":
            return []
        return [value] if isinstance(value, str) else list(value)

    def refresh_channel_choices(self) -> None:
        """
        Update dependent channel controls without emitting a cascade of edits.
        """
        if self.step == StepName.CONVERT:
            export = self.widgets.get("export_channels")
            if not isinstance(export, ExportChannelsWidget):
                return
            channels = self.adapter.source_channel_labels() or self.adapter.saved_image_channels
            previous = [export.itemText(index) for index in range(export.count())]
            saved = self.adapter.field_value(self.step, "export_channels")
            selected = channels if saved == "all" else self._selected_channel_labels(saved)
            selected = [channel for channel in channels if channel in selected or channel not in previous]
            export.set_channels(channels, selected)
            self.adapter.set_field_value(self.step, "export_channels", "all" if selected == channels else selected)
            return
        channels = self.adapter.exported_channel_labels()
        if not channels:
            if self.step == StepName.TRACK:
                self.refresh_tracking_channels()
            return
        for path, widget in self.widgets.items():
            if isinstance(widget, ChannelChoiceWidget):
                widget.set_channels(channels, self.adapter.field_value(self.step, path))
                self.adapter.set_field_value(self.step, path, widget.value())
            elif path == "exclude_channel" and isinstance(widget, ChannelSelectionWidget):
                selected = self._selected_channel_labels(self.adapter.field_value(self.step, path))
                widget.set_channels(channels, selected)
                self.adapter.set_field_value(self.step, path, widget.value() or "None")
        if self.step == StepName.SEGMENT:
            entries = self.adapter.segment_channels()
            for index, widgets in enumerate(self.channel_widgets):
                for path in ("channel", "nuclear_channel"):
                    choice = widgets[path]
                    if isinstance(choice, ChannelChoiceWidget):
                        choice.set_channels(channels, entries[index].get(path))
                        entries[index][path] = choice.value()
            self.adapter.set_segment_channels(entries)
        if self.step == StepName.TRACK:
            self.refresh_tracking_channels()

    def _add_track_postprocess_section(self, parent_layout: QVBoxLayout) -> None:
        """
        Explain optional stationary-cell repair and group its dependent controls.
        """
        toggle = BoolWidget(bool(self.adapter.field_value(self.step, "postprocess.enabled")))
        toggle.setText(field_label("postprocess.enabled"))
        toggle.setToolTip(field_tooltip(self.step, "postprocess.enabled"))
        toggle.value_changed.connect(lambda value: self._store_value("postprocess.enabled", value))
        self.widgets["postprocess.enabled"] = cast(ValueWidget, toggle)
        parent_layout.addWidget(toggle)
        self._field_rows.append(toggle)

        section = QGroupBox()
        section.setFlat(True)
        section.setAccessibleName(field_label("postprocess.enabled"))
        layout = QVBoxLayout(section)
        description = QLabel(
            "For cells that remain in approximately the same position. Uses IoU (intersection over union) "
            "tracking to reconnect fragmented tracks, removes inconsistent masks, and fills missing frames. "
            "Tracks with too few reliable "
            "observations are removed. Leave off for migrating cells.")
        description.setWordWrap(True)
        description.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(description)

        parameters = QWidget()
        parameter_form = QFormLayout(parameters)
        parameter_form.setContentsMargins(0, 4, 0, 0)
        explanations = (
            "Higher values reject more masks that differ from the cell's typical shape.",
            "Number of consistent observations needed to keep a track.",
            "Copies the first reliable mask into earlier frames.",
            "Copies the last reliable mask into later frames.",
        )
        self._add_fields(parameter_form, TRACK_POSTPROCESS_PARAMETERS,
                          dict(zip(TRACK_POSTPROCESS_PARAMETERS, explanations, strict=True)),
                          )
        self._track_postprocess_parameters = parameters
        layout.addWidget(parameters)
        parent_layout.addWidget(section)

    def _segmentation_channel_labels(self) -> list[str]:
        """
        Segmentation channel labels.
        """
        return list(dict.fromkeys(
            str(entry.get("channel", "")).strip()
            for entry in self.adapter.segment_channels()
            if str(entry.get("channel", "")).strip()))

    def refresh_tracking_channels(self) -> None:
        """
        Refresh choices from segmentation, selecting newly added channels.
        """
        widget = self.widgets.get("channel_to_track")
        if not isinstance(widget, ChannelSelectionWidget):
            return
        previous_options = [widget.itemText(index)
                            for index in range(widget.count())]
        selected = widget.value()
        channels = self._segmentation_channel_labels()
        selected.extend(channel for channel in channels
                        if channel not in previous_options)
        widget.set_channels(channels, selected)
        self.adapter.set_field_value(self.step, "channel_to_track", widget.value())
        self.value_changed.emit()

    def _build_channel_sections(self) -> None:
        """
        Build channel sections.
        """
        assert self._model_loader is not None
        model_options = self._model_loader.options
        model_path = model_setting_path()
        self.channel_widgets: list[dict[str, ValueWidget | ChannelChoiceWidget | ChannelSelectionWidget]] = []
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
            heading_size = max(1, round(self.fontInfo().pixelSize() * 1.15))
            heading_font = QFont(self.font())
            heading_font.setPixelSize(heading_size)
            heading_font.setBold(True)
            group.setFont(heading_font)
            body = QWidget()
            body_font = QFont(self.font())
            body_font.setBold(False)
            body_font.setPixelSize(self.fontInfo().pixelSize())
            body.setFont(body_font)
            group_layout = QVBoxLayout(group)
            group_layout.addWidget(body)
            form = QFormLayout(body)
            defaults = {"channel": "", "do_denoise": True, "nuclear_channel": "None",
                        model_path: model_options.default_model if model_options else '', "user_settings.diameter": 15,
                        "user_settings.flow_threshold": 0.4, "user_settings.cellprob_threshold": 0.0,
                        "user_settings.do_3D": False, "user_settings.stitch_threshold": 0.0}
            label_width = max(self.fontMetrics().horizontalAdvance(field_label(path))
                              for path in defaults) + 12
            for path, default in defaults.items():
                value = entry
                for part in path.split("."):
                    value = value.get(part, default) if isinstance(value, dict) else default
                if path == model_path and not value:
                    value = model_options.default_model if model_options else ''
                widget = (ChoiceWidget(str(value), model_options.built_in_models if model_options else ()) if path == model_path
                          else self._create_parameter_widget(path, "None" if value is None else value))
                if path == model_path and isinstance(widget, ChoiceWidget) and not model_options and not value:
                    widget.clear()
                    widget.setPlaceholderText('Loading models…')
                channel_widgets[path] = widget
                widget.setToolTip(field_tooltip(self.step, path))
                widget.value_changed.connect(lambda value, i=index, p=path: self._store_channel(i, p, value))
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
                    _add_parameter_row(form, "Channel to segment", row,
                                       field_tooltip(self.step, path), label_width,
                                       hint=field_hint(self.step, path),
                                       )
                else:
                    _add_parameter_row(form, field_label(path), widget,
                                       field_tooltip(self.step, path), label_width,
                                       hint=field_hint(self.step, path),
                                       )
            layout.addWidget(group)
        self.channel_sections.setEnabled(self._editable)
        if self._model_loader.error:
            self._model_choices_failed(self._model_loader.error)

    def _model_choices_ready(self, options: CellposeModelOptions) -> None:
        """
        Refresh only model dropdowns, preserving saved models and all other edits.
        """
        path = model_setting_path()
        for index, widgets in enumerate(self.channel_widgets):
            widget = widgets.get(path)
            if isinstance(widget, ChoiceWidget):
                current = widget.currentText()
                selected = current or options.default_model
                with QSignalBlocker(widget):
                    widget.clear()
                    widget.addItems(list(dict.fromkeys([selected, *options.built_in_models])))
                    widget.setCurrentText(selected)
                if not current:
                    self._store_channel(index, path, selected)

    def _model_choices_failed(self, error: str) -> None:
        """
        Keep saved models usable and explain failed discovery beside the model control.
        """
        path = model_setting_path()
        for widgets in self.channel_widgets:
            widget = widgets.get(path)
            if isinstance(widget, ChoiceWidget):
                widget.setPlaceholderText('Models unavailable')
                widget.setToolTip(f'Could not load Cellpose models: {error}. Saved settings are preserved.')

    def _store_channel(self, index: int, path: str, value: object) -> None:
        """
        Store channel.
        """
        entries = self.adapter.segment_channels()
        node = entries[index]
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.adapter.set_segment_channels(entries)
        self.value_changed.emit()

    def _add_channel(self, index: int) -> None:
        """
        Add channel.
        """
        entries = self.adapter.segment_channels()
        entry = deepcopy(entries[index])
        entry["channel"] = ""
        entry["nuclear_channel"] = "None"
        entries.insert(index + 1, entry)
        self.adapter.set_segment_channels(entries)
        self._build_channel_sections()
        self.value_changed.emit()

    def _remove_channel(self, index: int) -> None:
        """
        Remove channel.
        """
        entries = self.adapter.segment_channels()
        if len(entries) > 1:
            entries.pop(index)
            self.adapter.set_segment_channels(entries)
            self._build_channel_sections()
            self.value_changed.emit()

    def _store_value(self, path: str, value: object) -> None:
        """
        Store an edited value and refresh dependent preset and runtime fields.
        """
        if self.step == StepName.CONVERT and path == "export_channels":
            channels = self.adapter.source_channel_labels() or self.adapter.saved_image_channels
            value = "all" if value == channels else value
        if path == "exclude_channel" and not value:
            value = "None"
        self.adapter.set_field_value(self.step, path, value)
        if self.step == StepName.CONVERT and path == "channel_labels":
            self.refresh_channel_choices()
        if path == "context" and self.step in (StepName.REGISTER_TIME, StepName.REGISTER_CHANNEL):
            plan = resolve_registration_plan(cast(RegistrationContext, value))
            for name, resolved in (("algorithm", plan.algorithm), ("method", plan.method)):
                self.adapter.set_field_value(self.step, name, resolved)
                widget = self.widgets.get(name)
                if isinstance(widget, ChoiceWidget):
                    with QSignalBlocker(widget):
                        widget.setCurrentText(resolved)
        self._update_worker_state()
        self._update_mask_request_state()
        self._update_track_postprocess_state()
        self.value_changed.emit()

    def show_advanced_settings(self) -> None:
        """
        Reveal the effective manual settings after accepting a tuner result.
        """
        self._advanced_group.setChecked(True)

    @property
    def advanced_settings_visible(self) -> bool:
        """
        Report whether advanced controls should stay expanded after a rebuild.
        """
        return self._advanced_group.isChecked()

    def sync_to_adapter(self) -> None:
        """
        Sync to adapter.
        """
        for path, widget in self.widgets.items():
            value = widget.value()
            if self.step == StepName.CONVERT and path == "export_channels":
                channels = self.adapter.source_channel_labels() or self.adapter.saved_image_channels
                value = "all" if value == channels else value
            if path == "exclude_channel" and not value:
                value = "None"
            self.adapter.set_field_value(self.step, path, value)
        for index, widgets in enumerate(getattr(self, "channel_widgets", [])):
            for path, widget in widgets.items():
                self._store_channel(index, path, widget.value())

    def _update_worker_state(self) -> None:
        """
        Update worker state.
        """
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
        """
        Set editable.
        """
        self._editable = editable
        with QSignalBlocker(self.enable_group):
            self.enable_group.setChecked(editable)
        if hasattr(self, "channel_sections"):
            self.channel_sections.setEnabled(editable)
        self._refresh_enabled_states()

    def _update_mask_request_state(self) -> None:
        """
        Update mask request state.
        """
        for toggle_path, count_path in (
                ("draw_ref_mask", "expected_ref_masks"),
                ("draw_roi_mask", "expected_roi_masks")):
            toggle = self.widgets.get(toggle_path)
            count = self.widgets.get(count_path)
            if count is not None:
                count.setEnabled(self._editable and (toggle is None or bool(toggle.value())))

    def _update_track_postprocess_state(self) -> None:
        """
        Update track postprocess state.
        """
        toggle = self.widgets.get("postprocess.enabled")
        if toggle is None:
            return
        parameters_enabled = (
            self._editable
            and bool(toggle.value())
        )
        if self._track_postprocess_parameters is not None:
            self._track_postprocess_parameters.setEnabled(parameters_enabled)
        for path in TRACK_POSTPROCESS_PARAMETERS:
            parameter = self.widgets.get(path)
            if parameter is not None:
                parameter.setEnabled(parameters_enabled)

    def _refresh_enabled_states(self) -> None:
        """
        Refresh enabled states.
        """
        for row in self._field_rows:
            row.setEnabled(self._editable)
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

    def showEvent(self, event: QShowEvent) -> None:
        """
        Refresh controls when the widget becomes visible.
        """
        self._update_worker_state()
        super().showEvent(event)


class RuntimeSettingsEditor(QWidget):
    """Edit the application-level runtime options."""

    value_changed = Signal()

    def __init__(self, adapter: SettingsAdapter, parent: QWidget | None = None) -> None:
        """
        Initialize the RuntimeSettingsEditor state and dependencies.
        """
        super().__init__(parent)
        self.adapter = adapter
        self.widgets: dict[str, ValueWidget] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        group = CollapsibleAdvancedGroup("Advanced runtime settings")
        policy = group.content.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        group.content.setSizePolicy(policy)
        form = group.form
        form.setVerticalSpacing(8)
        names = (
            "execution", "console_level", "file_level", "log_dir", "unlock_all_tabs"
        )
        label_width = max(self.fontMetrics().horizontalAdvance(field_label(name))
                          for name in names) + 12
        for name in names:
            widget = create_field_widget(adapter.runtime_value(name), RUNTIME_CHOICES.get(name))
            tooltip = runtime_field_tooltip(name)
            widget.setToolTip(tooltip)
            if name == "log_dir" and isinstance(widget, TextWidget):
                widget.setPlaceholderText("Use run_dir/.fits (default)")
            widget.value_changed.connect(lambda value, field_name=name: self._store_value(field_name, value))
            hint = {"execution": "Batch finishes each step; conveyor overlaps ready work.",
                    "log_dir": "Leave blank to use run_dir/.fits for logs and reports.",
                    }.get(name)
            _add_parameter_row(form, field_label(name), widget, tooltip, label_width, hint=hint)
            self.widgets[name] = widget
        group.toggled.connect(self._set_fields_enabled)
        self._advanced_group = group
        outer.addWidget(group)
        self._set_fields_enabled(group.isChecked())

    def _store_value(self, name: str, value: object) -> None:
        """
        Store value.
        """
        self.adapter.set_runtime_value(name, value)
        self.value_changed.emit()

    def _set_fields_enabled(self, enabled: bool) -> None:
        """
        Set fields enabled.
        """
        for widget in self.widgets.values():
            widget.setEnabled(enabled)

    def sync_to_adapter(self) -> None:
        """
        Sync to adapter.
        """
        for name, widget in self.widgets.items():
            self.adapter.set_runtime_value(name, widget.value())
