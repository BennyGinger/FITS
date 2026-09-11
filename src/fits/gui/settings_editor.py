from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from fits.environment.constant import StepName
from fits.gui.field_widgets import IntWidget, TextWidget, ValueWidget, create_field_widget
from fits.gui.settings_adapter import (
    RUNTIME_CHOICES,
    STEP_LAYOUTS,
    SettingsAdapter,
    field_choices,
    field_label,
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
            widget = create_field_widget(value, field_choices(self.step, path))
            widget.setToolTip(path)
            if path in ("expected_ref_masks", "expected_roi_masks") and isinstance(widget, IntWidget):
                widget.setMinimum(1 if path == "expected_ref_masks" else 0)
                widget.setToolTip("Initial number of masks to request per experiment.")
            elif path in ("draw_ref_mask", "draw_roi_mask"):
                widget.setToolTip(
                    "Request interactive drawing. Existing saved masks are used automatically.")
            widget.value_changed.connect(
                lambda changed_value, field_path=path: self._store_value(
                    field_path, changed_value
                )
            )
            form.addRow(field_label(path), widget)
            self.widgets[path] = widget

    def _store_value(self, path: str, value: object) -> None:
        self.adapter.set_field_value(self.step, path, value)
        self._update_worker_state()
        self._update_mask_request_state()
        self.value_changed.emit()

    def sync_to_adapter(self) -> None:
        for path, widget in self.widgets.items():
            self.adapter.set_field_value(self.step, path, widget.value())

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
            workers.setToolTip(
                "Ignored during serial execution." if is_serial else "workers"
            )

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self._refresh_enabled_states()

    def _update_mask_request_state(self) -> None:
        for toggle_path, count_path in (
                ("draw_ref_mask", "expected_ref_masks"),
                ("draw_roi_mask", "expected_roi_masks")):
            toggle = self.widgets.get(toggle_path)
            count = self.widgets.get(count_path)
            if count is not None:
                count.setEnabled(self._editable and (toggle is None or toggle.value()))

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
            if name == "log_dir" and isinstance(widget, TextWidget):
                widget.setPlaceholderText("Use run_dir/logs (default)")
                widget.setToolTip("Optional log root. FITS creates a logs folder inside it; blank uses the run directory.")
            elif name == "unlock_all_tabs":
                widget.setToolTip(
                    "Show all phase settings before converted arrays exist. "
                    "Image viewers still require a real fits_array.tif file.")
            widget.value_changed.connect(
                lambda value, field_name=name: self._store_value(field_name, value))
            form.addRow(field_label(name), widget)
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
