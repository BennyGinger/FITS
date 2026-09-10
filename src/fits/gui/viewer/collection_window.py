"""Previewable mask collection UI. Pipeline scheduling is deliberately external."""
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent, QPalette
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QStyle, QMessageBox, QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget

from fits.gui.viewer.mask_window import MaskDrawingWindow
from fits.sessions.collection import MaskCollectionRequest, MaskCollectionOutcome
from fits.settings.models import DistanceProfileSettings, ExtractSettings
from fits.tasks.reference_mask import ReferenceMaskSession
from fits.tasks.roi_mask import RoiSession


class MaskCollectionWindow(MaskDrawingWindow):
    """One active experiment, an append-only waiting queue, and explicit outcomes."""

    source_panel_sizes = (430, 590)

    experiment_finalized = Signal(object)
    collection_finished = Signal()
    cancellation_requested = Signal()

    def __init__(self, parent=None, *, preview: bool = False,
                 extraction: ExtractSettings | None = None,
                 profile: DistanceProfileSettings | None = None,
                 run_dir: Path | None = None) -> None:
        self.run_dir = Path(run_dir).resolve() if run_dir is not None else None
        self._preview = preview
        self._preview_extraction = extraction
        self._preview_profile = profile
        self._waiting: deque[MaskCollectionRequest] = deque()
        self._seen: set[Path] = set()
        self._requests: dict[Path, MaskCollectionRequest] = {}
        self._resolved: set[Path] = set()
        self._inspection: ReferenceMaskSession | RoiSession | None = None
        self._return_view: tuple[str, int, int, tuple[float, float], NDArray[np.uint8] | None] | None = None
        self._active: MaskCollectionRequest | None = None
        self._collapse_source: Path | None = None
        self._input_complete = False
        self._ended = False
        self._completed = 0
        self._baseline: dict[str, NDArray[np.uint8]] = {}
        self._baseline_labels: dict[str, str] = {}
        self._label_suggestions = {"reference": "", "roi": ""}
        self._canvas_dirty: set[str] = set()
        self._saved: dict[str, set[Path]] = {"reference": set(), "roi": set()}
        self._skipped = {"reference": 0, "roi": 0}
        self._finished_modes: set[str] = set()
        super().__init__(parent=parent)
        self.setWindowTitle("FITS Mask Collection" + (" — Preview" if preview else ""))
        self.tool_tabs.tabBar().hide()
        self.mask_saved.connect(self._saved_mask)
        self.image_viewer.drawing_started.connect(self._drawing_started)
        self._refresh_collection()

    def _build_source_controls(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.preview_note = QLabel(
            "Preview only — no pipeline is running.\nSaving writes masks to the selected experiment folder.")
        self.preview_note.setWordWrap(True)
        self.preview_note.setVisible(self._preview)
        layout.addWidget(self.preview_note)
        self.load_button = QPushButton("Load test experiments…")
        self.load_button.setVisible(self._preview)
        self.load_button.clicked.connect(self._load_test_experiments)
        layout.addWidget(self.load_button)
        self.experiment_label = QLabel()
        self.count_label = QLabel()
        layout.addWidget(self.experiment_label)
        layout.addWidget(self.count_label)
        self.expected_labels = {}
        self.expected_buttons = {}
        for kind in ("reference", "roi"):
            row = QHBoxLayout()
            label = QLabel()
            self.expected_labels[kind] = label
            row.addWidget(label)
            for delta, symbol in ((-1, "−"), (1, "+")):
                button = QToolButton()
                button.setText(symbol)
                button.setToolTip(f"{'Increase' if delta > 0 else 'Decrease'} the expected {kind} mask count. Saved masks and drawings are kept.")
                button.clicked.connect(lambda checked=False, k=kind, d=delta: self._change_expected(k, d))
                self.expected_buttons[kind, delta] = button
                row.addWidget(button)
            row.addStretch(1)
            layout.addLayout(row)
        self.experiment_tree = QTreeWidget()
        self.experiment_tree.setHeaderHidden(True)
        self.experiment_tree.setMinimumHeight(60)
        self.experiment_tree.setToolTip(
            "Expand an experiment to see its saved masks. Click a mask to open it. "
            "The highlighted folder is the current drawing experiment.")
        self.experiment_tree.itemClicked.connect(self._tree_mask_selected)
        self.experiment_tree.itemActivated.connect(self._tree_mask_selected)
        layout.addWidget(self.experiment_tree, 1)
        self.return_button = QPushButton("Return to current experiment")
        self.return_button.setToolTip("Return to your current drawing without changing the experiment queue.")
        self.return_button.clicked.connect(self._return_to_current)
        self.return_button.hide()
        layout.addWidget(self.return_button)
        self.switch_button = QPushButton("Go to ROI")
        self.switch_button.clicked.connect(
            lambda: self.switch_mode("roi" if self._kind() == "reference" else "reference"))
        self.mode_label = QLabel("Current mode: REFERENCE")
        self.finish_mode_button = QPushButton("Finish reference masks")
        self.finish_mode_button.clicked.connect(self._finish_mode)
        finish_mode_row = QHBoxLayout()
        finish_mode_row.addWidget(self.finish_mode_button)
        self.next_button = QPushButton("Next experiment")
        self.next_button.clicked.connect(self._finish_experiment)
        finish_mode_row.addWidget(self.next_button)
        layout.addLayout(finish_mode_row)
        layout.addWidget(self.switch_button)
        self.finish_button = QPushButton("Finish drawing")
        self.finish_button.clicked.connect(self._finish_drawing)

        self.quit_button = QPushButton("Quit pipeline")
        self.quit_button.setStyleSheet("background-color: #a52a2a; color: white; font-weight: bold;")
        self.quit_button.clicked.connect(self.close)

        descriptions = {
            self.load_button: "Preview only: add prepared experiments from a folder. In the pipeline, experiments arrive automatically.",
            self.next_button: "Finish the current experiment and open the next one. You will be warned about unsaved work or missing masks.",
            self.finish_button: "End the drawing session. Confirmation is needed if drawings remain or work is unsaved. The pipeline continues.",
            self.quit_button: ("Close this preview after confirmation. No pipeline is running."
                               if self._preview else "Stop the entire pipeline after confirmation. Unsaved drawing changes will be lost."),
        }
        for button, description in descriptions.items():
            button.setToolTip(description)
        return panel

    def _connect_source_controls(self) -> None:
        # The coordinator supplies images; no directory-browser signals here.
        pass

    def eventFilter(self, watched, event) -> bool:
        # QTabWidget normally switches pages with Ctrl+Tab, even with a hidden bar.
        if (isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)):
            return True
        return super().eventFilter(watched, event)

    @Slot(object)
    def enqueue_experiment(self, request: MaskCollectionRequest) -> None:
        """Call on the GUI thread, or connect a worker's queued signal to this slot."""
        if self._ended or self._input_complete:
            raise RuntimeError("Mask collection is no longer accepting requests.")
        key = request.image_path
        if key in self._seen:
            return
        self._seen.add(key)
        self._requests[key] = request
        self._waiting.append(request)
        if self._active is None:
            self._activate_next()
        self._refresh_collection()

    @Slot()
    def no_more_requests(self) -> None:
        self._input_complete = True
        self._refresh_collection()
        self._complete_if_idle()

    def _activate_next(self) -> None:
        # Suggest names only; never carry drawing pixels to another experiment.
        if self._source_path is not None:
            for kind in ("reference", "roi"):
                paths = sorted(self._saved[kind])
                if paths:
                    prefix = "fits_ref_" if kind == "reference" else "fits_roi_"
                    labels = [path.stem.removeprefix(prefix) for path in paths]
                    current_label = self._session_panel(kind)[1].label_edit.text()
                    self._label_suggestions[kind] = (
                        current_label if kind == "roi" and current_label in labels else labels[0])
        if not self._waiting:
            self._active = None
            self._close_session()
            return
        if self._inspection is not None:
            self._return_to_current()
        if self._active is not None:
            self._collapse_source = self._active.image_path
        self._active = self._waiting.popleft()
        self._finished_modes.clear()
        self._skipped = {"reference": 0, "roi": 0}
        self._targets = {"reference": self._active.expected_ref_masks,
                         "roi": self._active.expected_roi_masks}
        self.tool_tabs.setCurrentWidget(self.reference_panel)
        self._open_source(self._active.image_path)
        self._saved = {
            "reference": {p for p in self._active.image_path.parent.glob("fits_ref_*.tif") if p.is_file()},
            "roi": {p for p in self._active.image_path.parent.glob("fits_roi_*.tif") if p.is_file()}}
        self._canvas_dirty.clear()
        self._baseline.clear()
        self._baseline_labels.clear()
        for kind in ("reference", "roi"):
            session, panel = self._session_panel(kind)
            if session is not None and not panel.label_edit.text():
                panel.label_edit.setText(self._label_suggestions[kind])
            self._remember(kind)

    def _kind(self) -> str:
        return "reference" if self._reference_tool_active() else "roi"

    def _session_panel(self, kind):
        return ((self._reference_session, self.reference_panel) if kind == "reference"
                else (self._roi_session, self.roi_panel))

    def _remember(self, kind) -> None:
        session, panel = self._session_panel(kind)
        if session is not None:
            self._baseline[kind] = session.mask_array
            self._baseline_labels[kind] = panel.label_edit.text()
        self._canvas_dirty.discard(kind)

    def _drawing_started(self) -> None:
        self._canvas_dirty.add(self._kind())
        self._finished_modes.discard(self._kind())

    def _dirty(self, kind) -> bool:
        session, panel = self._session_panel(kind)
        baseline = self._baseline.get(kind)
        return session is not None and (
            kind in self._canvas_dirty
            or baseline is None
            or not np.array_equal(session.mask_array, baseline)
            or panel.label_edit.text() != self._baseline_labels.get(kind, ""))

    def _confirm(self, title: str, message: str) -> bool:
        return QMessageBox.warning(self, title, message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok

    def _discard(self, kind) -> None:
        assert self._source_path is not None
        if kind == "reference":
            self._reference_session = ReferenceMaskSession(self._source_path, reference_path=self._reference_path)
            self._image_session = self._reference_session
            self.reference_panel.label_edit.setText(self._reference_session.reference_label or "")
        else:
            self._roi_session = RoiSession(self._source_path, roi_path=self._roi_path)
            self.roi_panel.label_edit.setText(self._roi_session.roi_label or "")
            self.roi_panel.reset_for_source()
        self._remember(kind)
        self._display_selection()

    def _allow_discard(self, kinds) -> bool:
        dirty = [kind for kind in kinds if self._dirty(kind)]
        if dirty and not self._confirm("Unsaved mask changes",
                "Save your work first, otherwise your unsaved changes will be lost.\n\n"
                "Cancel returns to drawing. OK discards the changes and continues."):
            return False
        for kind in dirty:
            self._discard(kind)
        return True

    def switch_mode(self, kind: str) -> None:
        if kind not in ("reference", "roi"):
            raise ValueError(f"Unknown drawing mode: {kind}")
        if self._active is None or self._ended or kind == self._kind():
            return
        if not self._allow_discard((self._kind(),)):
            return
        self.tool_tabs.setCurrentWidget(self._session_panel(kind)[1])
        self._refresh_collection()

    def _saved_mask(self, kind: str, path: Path) -> None:
        self._saved[kind].add(path)
        if kind == "reference":
            self._reference_path = path
        else:
            self._roi_path = path
        # A save writes only the selected channel. Other channels may still be unsaved.
        session, panel = self._session_panel(kind)
        if session is None:
            return
        current = session.mask_array
        baseline = self._baseline[kind]
        if "C" in session.axes:
            selection: list[slice | int] = [slice(None)] * current.ndim
            selection[session.axes.index("C")] = session.channel_labels.index(self.channel_combo.currentText())
            baseline[tuple(selection)] = current[tuple(selection)]
        else:
            baseline[...] = current
        self._baseline_labels[kind] = panel.label_edit.text()
        self._canvas_dirty.discard(kind)
        self._finished_modes.discard(kind)
        self._refresh_collection()

    def _new_mask(self) -> None:
        kind = self._kind()
        if not self._allow_discard((kind,)):
            return
        if kind == "reference":
            self._reference_path = None
        else:
            self._roi_path = None
        self._discard(kind)
        self._finished_modes.discard(kind)
        self._refresh_collection()

    def _build_mode_controls(self, layout) -> None:
        layout.addWidget(self.mode_label, 0, Qt.AlignmentFlag.AlignCenter)

    def _build_viewer_actions(self, layout) -> None:
        layout.addSpacing(24)
        self.saving_stack = QStackedWidget()
        for panel in (self.reference_panel, self.roi_panel):
            panel.outer_layout.removeWidget(panel.saving_section)
            panel.label_edit.setMinimumWidth(240)
            panel.label_edit.setMaximumWidth(16777215)
            panel.save_button.setFixedWidth(100)
            panel.save_row.setStretch(1, 1)
            panel.save_row.setStretch(2, 0)
            panel.saving_section.setMinimumHeight(94)
            self.saving_stack.addWidget(panel.saving_section)
        layout.addWidget(self.saving_stack, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(24)
        buttons = QVBoxLayout()
        buttons.addWidget(self.finish_button)
        buttons.addWidget(self.quit_button)
        layout.addLayout(buttons)
        layout.setAlignment(buttons, Qt.AlignmentFlag.AlignVCenter)

    def _change_expected(self, kind: str, delta: int) -> None:
        if self._active is None or self._ended or self._inspection is not None:
            return
        minimum = max(len(self._saved[kind]), int(kind == "reference" and self._active.requires_reference))
        self._targets[kind] = max(minimum, self._targets[kind] + delta)
        self._finished_modes.discard(kind)
        self._refresh_collection()

    def _confirm_missing(self, kinds) -> bool:
        if self._active is None:
            return True
        notes = []
        for kind in kinds:
            remaining = max(0, self._targets[kind] - len(self._saved[kind]) - self._skipped[kind])
            if remaining:
                notes.append(f"{remaining} expected {kind} mask(s) remain. They will be skipped.")
        if "reference" in kinds and self._active.requires_reference and not self._saved["reference"]:
            notes.append("There is no reference mask. Distance profiling cannot run for this experiment.")
        if "roi" in kinds and self._active.uses_roi and not self._saved["roi"]:
            notes.append("There is no ROI mask. Distance profiling will use the whole image.")
        return not notes or self._confirm("Finish mask collection?", "\n\n".join(notes))

    def _finish_mode(self) -> None:
        kind = self._kind()
        if not self._confirm_missing((kind,)) or not self._allow_discard((kind,)):
            return
        self._skipped[kind] = max(self._skipped[kind], self._targets[kind] - len(self._saved[kind]))
        self._finished_modes.add(kind)
        self._refresh_collection()

    def _outcome(self, request, saved, skipped) -> MaskCollectionOutcome:
        return MaskCollectionOutcome(request, tuple(sorted(saved["reference"])),
                                     tuple(sorted(saved["roi"])), skipped["reference"], skipped["roi"])

    def _finish_experiment(self) -> bool:
        if self._active is None:
            return True
        kinds = tuple(kind for kind in ("reference", "roi") if kind not in self._finished_modes)
        completed = not self._waiting and self._all_expected_done()
        if (not completed and not self._confirm_missing(kinds)) or not self._allow_discard(("reference", "roi")):
            return False
        for kind in kinds:
            self._skipped[kind] = max(self._skipped[kind], self._targets[kind] - len(self._saved[kind]))
        self.experiment_finalized.emit(self._outcome(self._active, self._saved, self._skipped))
        self._resolved.add(self._active.image_path)
        self._completed += 1
        self._activate_next()
        self._refresh_collection()
        self._complete_if_idle()
        return True

    def _complete_if_idle(self) -> None:
        if (not self._ended and self._requests and self._active is None
                and not self._waiting and (self._input_complete or self._preview)):
            self._ended = True
            self.collection_finished.emit()
            self.close()

    def _all_expected_done(self) -> bool:
        if not (self._input_complete or self._preview):
            return False
        if any(self._dirty(kind) for kind in ("reference", "roi")):
            return False
        for request in ([self._active] if self._active else []) + list(self._waiting):
            if request == self._active:
                refs, rois = len(self._saved["reference"]), len(self._saved["roi"])
                ref_target, roi_target = self._targets["reference"], self._targets["roi"]
            else:
                folder = request.image_path.parent
                refs = sum(p.is_file() for p in folder.glob("fits_ref_*.tif"))
                rois = sum(p.is_file() for p in folder.glob("fits_roi_*.tif"))
                ref_target, roi_target = request.expected_ref_masks, request.expected_roi_masks
            if refs < max(ref_target, int(request.requires_reference)) or rois < roi_target:
                return False
        return True

    def _experiment_name(self, request) -> str:
        if self.run_dir is not None:
            try:
                relative = request.image_path.parent.relative_to(self.run_dir)
                return relative.as_posix() if relative.parts else self.run_dir.name
            except ValueError:
                return request.image_path.parent.name
        return request.experiment_id

    def _finish_drawing(self) -> None:
        if not self._all_expected_done() and not self._confirm("Finish drawing?",
                "End this drawing session? Remaining requests will be skipped.\n"
                "The pipeline will continue where its required masks are available.\n"
                "Experiments without an ROI use the whole image; without a reference, distance profiling cannot run."):
            return
        if not self._allow_discard(("reference", "roi")):
            return
        if self._active:
            for kind in ("reference", "roi"):
                self._skipped[kind] = max(self._skipped[kind], self._targets[kind] - len(self._saved[kind]))
            self.experiment_finalized.emit(self._outcome(self._active, self._saved, self._skipped))
        # Preserve existing artifacts for unvisited experiments; skip only unmet targets.
        for request in self._waiting:
            folder = request.image_path.parent
            references = tuple(sorted(p for p in folder.glob("fits_ref_*.tif") if p.is_file()))
            rois = tuple(sorted(p for p in folder.glob("fits_roi_*.tif") if p.is_file()))
            self.experiment_finalized.emit(MaskCollectionOutcome(
                request, references, rois,
                max(0, request.expected_ref_masks - len(references)),
                max(0, request.expected_roi_masks - len(rois))))
        self._resolved.update(self._requests)
        self._waiting.clear()
        self._active = None
        self._ended = True
        self._close_session()
        self.collection_finished.emit()
        self._refresh_collection()
        self.close()

    def _refresh_experiment_tree(self) -> None:
        tree = self.experiment_tree
        expanded = set()
        selected = tree.currentItem().data(0, Qt.ItemDataRole.UserRole) if tree.currentItem() else None
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item is None:
                continue
            key = item.data(0, Qt.ItemDataRole.UserRole)[0]
            if item.isExpanded():
                expanded.add(key)
        expanded.discard(self._collapse_source)
        self._collapse_source = None
        tree.clear()
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        mask_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        for source, request in self._requests.items():
            current = self._active is not None and source == self._active.image_path
            status = "current" if current else "finished" if source in self._resolved else "waiting"
            parent = QTreeWidgetItem(tree, [f"{self._experiment_name(request)} — {status}"])
            parent.setData(0, Qt.ItemDataRole.UserRole, (source, None))
            parent.setIcon(0, folder_icon)
            parent.setToolTip(0, self._experiment_name(request))
            if current:
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                colour = QColor(self.palette().highlight().color())
                colour.setAlpha(85)
                parent.setBackground(0, colour)
            for pattern in ("fits_ref_*.tif", "fits_roi_*.tif"):
                for path in sorted(source.parent.glob(pattern)):
                    if not path.is_file():
                        continue
                    item = QTreeWidgetItem(parent, [path.name])
                    item.setIcon(0, mask_icon)
                    item.setData(0, Qt.ItemDataRole.UserRole, (source, path))
                    item.setToolTip(0, "Open this mask for editing." if current else
                                    "View this saved mask without changing the current drawing experiment.")
                    if selected == (source, path):
                        tree.setCurrentItem(item)
            parent.setExpanded(source in expanded or current)

    def _tree_mask_selected(self, item, column=0) -> None:
        source, path = item.data(0, Qt.ItemDataRole.UserRole)
        if path is None:
            return
        kind = "reference" if path.name.startswith("fits_ref_") else "roi"
        try:
            candidate = (ReferenceMaskSession(source, reference_path=path) if kind == "reference"
                         else RoiSession(source, roi_path=path))
        except Exception as error:
            self.status_label.setText(f"Could not open {path.name}: {error}")
            return
        current = self._active is not None and source == self._active.image_path and not self._ended
        if not current:
            self._inspect_mask(candidate, path)
            return
        if self._inspection is not None:
            self._return_to_current()
        if not self._allow_discard(tuple(dict.fromkeys((self._kind(), kind)))):
            return
        if kind == "reference" and isinstance(candidate, ReferenceMaskSession):
            self._reference_session = candidate
            self._reference_path = path
            self._image_session = candidate
            self.reference_panel.label_edit.setText(candidate.reference_label)
        elif isinstance(candidate, RoiSession):
            self._roi_session = candidate
            self._roi_path = path
            self.roi_panel.label_edit.setText(candidate.roi_label)
            self.roi_panel.reset_for_source()
        self._remember(kind)
        self.tool_tabs.setCurrentWidget(self._session_panel(kind)[1])
        if candidate.loaded_channels:
            self.channel_combo.setCurrentText(candidate.loaded_channels[0])
        self._display_selection()
        self.status_label.setText(f"Loaded {path.name} for editing.")
        self._refresh_collection()

    def _inspect_mask(self, session, path: Path) -> None:
        if self._inspection is None:
            self._return_view = (
                self.channel_combo.currentText(), self.frame_slider.value(), self.z_slider.value(),
                self.image_viewer.display_levels, self.image_viewer.drawing_mask.copy()
                if self._source_path is not None else None)
        self._inspection = session
        self._inspection_path = path
        blockers = [QSignalBlocker(widget) for widget in (self.channel_combo, self.frame_slider, self.z_slider)]
        self.channel_combo.clear()
        self.channel_combo.addItems(session.channel_labels)
        self.channel_combo.setCurrentText(session.loaded_channels[0])
        self.frame_slider.setRange(0, session.frame_count - 1)
        self.z_slider.setRange(0, session.plane_count - 1)
        self.frame_slider.setValue(0)
        self.z_slider.setValue(0)
        del blockers
        self.tool_panel.setEnabled(False)
        for widget in (self.channel_combo, self.frame_slider, self.z_slider):
            widget.setEnabled(True)
        self._display_selection()
        self.image_viewer.auto_scale()
        self.status_label.setText("Viewing a saved mask. Your current drawing is kept until you return.")
        self._refresh_collection()

    def _return_to_current(self) -> None:
        if self._inspection is None or self._return_view is None:
            return
        self._inspection = None
        channel, frame, z, levels, canvas = self._return_view
        self._return_view = None
        blockers = [QSignalBlocker(widget) for widget in (self.channel_combo, self.frame_slider, self.z_slider)]
        self.channel_combo.clear()
        session = self._image_session
        if session is not None:
            self.channel_combo.addItems(session.channel_labels)
            self.channel_combo.setCurrentText(channel)
            self.frame_slider.setRange(0, session.frame_count - 1)
            self.z_slider.setRange(0, session.plane_count - 1)
            self.frame_slider.setValue(frame)
            self.z_slider.setValue(z)
        del blockers
        self._set_source_controls_enabled(session is not None and not self._ended)
        if session is not None:
            self._display_selection()
            self.image_viewer.set_display_levels(levels)
            if canvas is not None:
                self.image_viewer.set_drawing_mask(canvas)
            self.status_label.setText("Returned to the current experiment.")
        else:
            self.image_viewer.image_item.clear()
            self.image_viewer.clear_mask()
        self._refresh_collection()

    def _display_selection(self) -> None:
        session = self._inspection
        if session is None:
            super()._display_selection()
            return
        if self.channel_combo.currentIndex() < 0:
            return
        frame, channel, z = self.frame_slider.value(), self.channel_combo.currentText(), self.z_slider.value()
        self.image_viewer.set_channel_lut(channel)
        self.image_viewer.set_image(session.display_frame(frame, channel, z))
        mask = (session.display_mask_plane(frame, channel, z) if isinstance(session, RoiSession)
                else session.mask_plane(frame, channel, z))
        self.image_viewer.set_drawing_mask(mask)
        self.image_viewer.set_drawing_enabled(False)
        self.image_viewer.set_mask_visible(self.show_mask.isChecked())
        self.image_viewer.set_mask_opacity(self.mask_opacity.value() / 100.0)
        self.frame_value.setText(f"{frame + 1} / {session.frame_count}")
        self.z_value.setText(f"{z + 1} / {session.plane_count}")

    def _tool_keypress(self, event) -> bool:
        if self._inspection is not None:
            return event.key() == Qt.Key.Key_S or bool(
                event.key() == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        return super()._tool_keypress(event)

    def _close_session(self) -> None:
        self._inspection = None
        self._return_view = None
        super()._close_session()

    def _apply_mode_appearance(self) -> None:
        kind = ("roi" if isinstance(self._inspection, RoiSession) else "reference"
                if self._inspection is not None else self._kind())
        background, accent, badge = (
            ("#172635", "#80b9f2", "#243e58") if kind == "reference"
            else ("#182e27", "#82d5b1", "#254c3c"))
        central = self.centralWidget()
        palette = central.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(background))
        central.setPalette(palette)
        central.setAutoFillBackground(True)
        self.tool_panel.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {accent}; background: {background}; }}")
        self.mode_label.setStyleSheet(
            f"background-color: {badge}; color: {accent}; border-left: 5px solid {accent}; "
            "padding: 4px 8px; font-weight: bold; font-size: 14px;")

    def _refresh_collection(self) -> None:
        if not hasattr(self, "experiment_label"):
            return
        active = self._active is not None and self._source_path is not None and not self._ended
        if self._ended:
            title = "Drawing session finished."
        elif self._active:
            title = f"Experiment {self._completed + 1}: {self._experiment_name(self._active)}"
        else:
            title = "All experiments finished." if self._input_complete else "Waiting for an experiment…"
        self.experiment_label.setText(title)
        self._refresh_experiment_tree()
        self.count_label.setText(f"{len(self._waiting)} experiment(s) waiting")
        for kind, label in self.expected_labels.items():
            saved = len(self._saved[kind]) if self._active else 0
            target = self._targets[kind] if self._active else 0
            label.setText(f"{'Ref' if kind == 'reference' else 'ROI'} expected: {target} · {saved} saved")
            minimum = max(saved, int(kind == "reference" and bool(self._active and self._active.requires_reference)))
            for delta in (-1, 1):
                self.expected_buttons[kind, delta].setEnabled(
                    active and self._inspection is None and (delta > 0 or target > minimum))
        kind = self._kind()
        self.saving_stack.setCurrentIndex(0 if kind == "reference" else 1)
        self.saving_stack.setEnabled(active and self._inspection is None)
        self._apply_mode_appearance()
        self.mode_label.setText(
            f"{'ROI' if isinstance(self._inspection, RoiSession) else 'REFERENCE'} — read-only"
            if self._inspection is not None else f"Current mode: {kind.upper()}")
        self.switch_button.setText("Go to ROI" if kind == "reference" else "Go to ref")
        self.switch_button.setToolTip(
            "Switch to ROI drawing. You will be warned before unsaved changes are discarded."
            if kind == "reference" else
            "Switch to reference drawing. You will be warned before unsaved changes are discarded.")
        mode_name = "reference" if kind == "reference" else "ROI"
        self.finish_mode_button.setText(f"Finish {mode_name} masks")
        self.finish_mode_button.setToolTip(
            f"Finish {kind} masks for this experiment. Remaining requests need confirmation; you can still switch modes.")
        self.return_button.setText("Return to current experiment" if self._active else "Return to collection")
        self.return_button.setVisible(self._inspection is not None)
        active = active and self._inspection is None
        for button in (self.switch_button, self.finish_mode_button, self.next_button):
            button.setEnabled(active)
        self.finish_button.setEnabled(not self._ended and self._inspection is None)
        self.load_button.setEnabled(not self._ended and not self._input_complete)

    def load_test_experiments(self, directory: Path) -> None:
        if self.run_dir is None:
            self.run_dir = directory.resolve()
        for source in sorted(directory.rglob("fits_array.tif")):
            if source.is_file():
                self.enqueue_experiment(MaskCollectionRequest.from_settings(
                    source, extraction=self._preview_extraction, profile=self._preview_profile))

    def _load_test_experiments(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose test experiments")
        if directory:
            self.load_test_experiments(Path(directory))

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._ended:
            message = ("Close this preview? Unsaved changes will be lost. No pipeline is running."
                       if self._preview else "Quit the pipeline? Unsaved changes will be lost and the run will stop.")
            if not self._confirm("Quit pipeline?" if not self._preview else "Close preview?", message):
                event.ignore()
                return
            self._ended = True
            self.cancellation_requested.emit()
        super().closeEvent(event)
