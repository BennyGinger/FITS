"""Qt-free registration tuning with projected fitting and disk-backed previews."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from numpy.typing import NDArray
from stackalign import RegisterModel, TransformModel
from stackalign.planes import fit_planes

from fits.interaction import FitsImageSession
from fits.interaction.planes import disk_empty
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.tasks.registration.tuned import (
    Mode, RegistrationSettings, TunedRegistration, fitting_signature, load_tuning, save_tuning)


@dataclass
class RegistrationPreview:
    key: str
    result: TunedRegistration
    array: NDArray


class RegistrationTuningSession(FitsImageSession):
    """Keep one original image and at most one preview per registration mode."""

    def __init__(self, source_path: str | Path) -> None:
        super().__init__(source_path)
        parent = self.source_path.parent / ".fits" / "viewer_cache" / "registration"
        parent.mkdir(parents=True, exist_ok=True)
        self._temporary = TemporaryDirectory(prefix="preview-", dir=parent)
        self._previews: dict[Mode, RegistrationPreview] = {}
        self._generation = 0
        stat = self.source_path.stat()
        self._source_stamp = stat.st_size, stat.st_mtime_ns

    @staticmethod
    def preview_key(settings: RegistrationSettings, upstream: RegisterTimeSettings | None) -> str:
        return json.dumps({"settings": settings.to_payload_dict(),
                           "upstream": upstream.to_payload_dict() if upstream is not None else None},
                          sort_keys=True)

    def cached_preview(self, mode: Mode, settings: RegistrationSettings,
                       upstream: RegisterTimeSettings | None = None) -> RegistrationPreview | None:
        preview = self._previews.get(mode)
        return preview if preview is not None and preview.key == self.preview_key(settings, upstream) else None

    def run_preview(self, mode: Mode, settings: RegistrationSettings, *,
                    upstream: RegisterTimeSettings | None = None,
                    progress: Callable[[str, int, int], None] | None = None,
                    cancelled: Callable[[], bool] | None = None) -> RegistrationPreview:
        stat = self.source_path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self._source_stamp:
            raise ValueError("The source image changed. Reopen the experiment before tuning.")
        existing = self.cached_preview(mode, settings, upstream)
        if existing is not None:
            return existing
        preceding = (self.run_preview("time", upstream, progress=progress, cancelled=cancelled)
                     if mode == "channel" and upstream is not None else None)

        def update(message: str, done: int, total: int) -> None:
            if cancelled is not None and cancelled():
                raise InterruptedError("Registration preview cancelled.")
            if progress is not None:
                progress(message, done, total)

        def image(frame: int, channel: int, z: int) -> NDArray:
            if preceding is not None:
                return preceding.array[self._plane_selection(frame, channel, z)]
            return self.display_frame(frame, channel, z)

        plan = resolve_registration_plan(settings.context, settings.backend, settings.method)
        if plan.mode != mode:
            raise ValueError("Settings do not match the requested registration mode.")
        reference_channel = None
        if isinstance(settings, RegisterTimeSettings):
            if "T" not in self.axes:
                raise ValueError("Time registration requires an image with a T axis.")
            channel = self._resolve_channel(settings.fit_channel if settings.fit_channel is not None else 0)
            selections = [(frame, channel) for frame in range(self.frame_count)]
            reference = settings.reference_strategy
        else:
            if "C" not in self.axes or len(self.channel_labels) < 2:
                raise ValueError("Channel registration requires at least two image channels.")
            if settings.reference_channel is None:
                raise ValueError("Choose a reference channel.")
            reference_channel = self._resolve_channel(settings.reference_channel)
            self._validate_axis_index("T", settings.reference_frame, "Reference frame")
            selections = [(settings.reference_frame, channel) for channel in range(len(self.channel_labels))]
            reference = reference_channel
        fitting = disk_empty((len(selections), self._axis_size("Y"), self._axis_size("X")), np.float32)
        for index, (frame, channel) in enumerate(selections):
            update(f"Reading {mode} fitting planes", index, len(selections))
            projected = np.asarray(image(frame, channel, 0), dtype=np.float32).copy()
            for z in range(1, self.plane_count):
                np.maximum(projected, image(frame, channel, z), out=projected)
            fitting[index] = projected
        signature = fitting_signature(fitting, self.shape, self.axes, self.channel_labels, settings)
        accepted = load_tuning(self.source_path, mode)
        if (accepted is not None and accepted.signature == signature
                and len(accepted.register.model.transform) == len(fitting)):
            register = accepted.register
            update(f"Reusing tuned {mode} transforms", 1, 1)
        else:
            excluded = ([self._resolve_channel(label) for label in settings.exclude_channel]
                        if isinstance(settings, RegisterChannelSettings) and settings.exclude_channel else [])
            matrices = fit_planes(fitting, backend=plan.backend, method=plan.method,
                                  reference=reference, cancelled=cancelled, excluded=excluded,
                                  progress=lambda done, total: update(f"Fitting {mode} transforms", done, total))
            register = RegisterModel(plan.backend).set_model(
                TransformModel(mode, plan.method, matrices, reference_channel))
        self._generation += 1
        path = Path(self._temporary.name) / f"{mode}-{self._generation}.npy"
        output = np.lib.format.open_memmap(path, mode="w+", dtype=self._reader.reader.dtype,
                                          shape=self.shape)
        keys = self._planes.keys()
        total = self.frame_count * len(self.channel_labels) * self.plane_count
        try:
            for index, (frame, channel, z) in enumerate(keys):
                update(f"Preparing {mode} preview", index, total)
                output[self._plane_selection(frame, channel, z)] = register.apply_plane(
                    image(frame, channel, z), frame=frame, channel=channel)
            output.flush()
            update(f"{mode.capitalize()} preview ready", total, total)
        except BaseException:
            del output
            path.unlink(missing_ok=True)
            raise
        previous = self._previews.get(mode)
        preview = RegistrationPreview(self.preview_key(settings, upstream),
                                      TunedRegistration(settings.model_copy(deep=True), signature, register), output)
        self._previews[mode] = preview
        if previous is not None:
            old_path = Path(str(getattr(previous.array, "filename", "")))
            del previous
            if old_path.is_file():
                old_path.unlink()
        return preview

    def save_preview(self, preview: RegistrationPreview) -> Path:
        stat = self.source_path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self._source_stamp:
            raise ValueError("The source changed. Reopen and run a new preview before saving.")
        return save_tuning(self.source_path, preview.result)

    def close(self) -> None:
        self._previews.clear()
        self._temporary.cleanup()
        super().close()
