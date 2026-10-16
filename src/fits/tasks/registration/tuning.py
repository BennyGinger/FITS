"""Qt-free crop fitting and registration previews computed one plane at a time."""

from __future__ import annotations

from collections.abc import Callable
from collections import OrderedDict
from dataclasses import dataclass, field
import json
from pathlib import Path
from threading import RLock

import numpy as np
from numpy.typing import NDArray
from stackalign.planes import fit_planes

from fits.interaction import FitsImageSession
from fits.interaction.crop import CropBounds, validate_crop
from fits.interaction.planes import disk_empty
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan
from fits.tasks.registration.tuned import Mode, RegistrationSettings, TunedRegistration
from fits.tasks.registration.tuned import fitting_signature, full_image_model, load_tuning, save_tuning


@dataclass
class RegistrationPreview:
    """Fitted transforms and a bounded cache of requested full-image planes."""
    key: str
    result: TunedRegistration
    upstream: RegistrationPreview | None = None
    planes: OrderedDict[tuple[int, int, int], NDArray] = field(default_factory=OrderedDict)


class RegistrationTuningSession(FitsImageSession):
    """Keep one original image and at most one preview per registration mode."""

    def __init__(self, source_path: str | Path) -> None:
        """Open one source image without loading or allocating a complete stack."""
        super().__init__(source_path)
        self._previews: dict[Mode, RegistrationPreview] = {}
        self._preview_lock = RLock()
        stat = self.source_path.stat()
        self._source_stamp = stat.st_size, stat.st_mtime_ns

    @staticmethod
    def preview_key(settings: RegistrationSettings, upstream: RegisterTimeSettings | None,
                    crop: CropBounds | None = None, upstream_crop: CropBounds | None = None) -> str:
        """Identify settings and active fitting crops, including upstream time fitting."""
        return json.dumps({"settings": settings.to_payload_dict(),
                           "upstream": upstream.to_payload_dict() if upstream is not None else None,
                           "crop": crop, "upstream_crop": upstream_crop if upstream is not None else None},
                          sort_keys=True)

    def cached_preview(self, mode: Mode, settings: RegistrationSettings,
                       upstream: RegisterTimeSettings | None = None, *,
                       crop: CropBounds | None = None, upstream_crop: CropBounds | None = None) -> RegistrationPreview | None:
        """Return transforms only when settings and enabled crops still match."""
        preview = self._previews.get(mode)
        return preview if preview is not None and preview.key == self.preview_key(settings, upstream, crop, upstream_crop) else None

    def run_preview(self, mode: Mode, settings: RegistrationSettings, *,
                    upstream: RegisterTimeSettings | None = None,
                    crop: CropBounds | None = None, upstream_crop: CropBounds | None = None,
                    progress: Callable[[str, int, int], None] | None = None,
                    cancelled: Callable[[], bool] | None = None) -> RegistrationPreview:
        """Fit only the active rectangle; defer full-image application until navigation."""
        stat = self.source_path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self._source_stamp:
            raise ValueError("The source image changed. Reopen the experiment before tuning.")
        validate_crop(crop, self._axis_size("X"), self._axis_size("Y"))
        existing = self.cached_preview(mode, settings, upstream, crop=crop, upstream_crop=upstream_crop)
        if existing is not None:
            return existing
        preceding = (self.run_preview("time", upstream, crop=upstream_crop, progress=progress, cancelled=cancelled)
                     if mode == "channel" and upstream is not None else None)

        def update(message: str, done: int, total: int) -> None:
            """Relay fitting progress and check cancellation before each operation."""
            if cancelled is not None and cancelled():
                raise InterruptedError("Registration preview cancelled.")
            if progress is not None:
                progress(message, done, total)

        def image(frame: int, channel: int, z: int) -> NDArray:
            """Read an original or upstream-registered full-resolution plane."""
            if preceding is not None:
                return self.preview_frame(preceding, frame, channel, z)
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
        x0, y0, x1, y1 = crop or (0, 0, self._axis_size("X"), self._axis_size("Y"))
        fitting = disk_empty((len(selections), y1 - y0, x1 - x0), np.float32)
        for index, (frame, channel) in enumerate(selections):
            update(f"Reading {mode} fitting planes", index, len(selections))
            projected = np.asarray(image(frame, channel, 0)[y0:y1, x0:x1], dtype=np.float32).copy()
            for z in range(1, self.plane_count):
                np.maximum(projected, image(frame, channel, z)[y0:y1, x0:x1], out=projected)
            fitting[index] = projected
        signature = fitting_signature(fitting, self.shape, self.axes, self.channel_labels, settings, crop)
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
            register = full_image_model(matrices, backend=plan.backend, mode=mode, method=plan.method,
                                        reference_channel=reference_channel, crop=crop)
        update(f"{mode.capitalize()} transforms ready; preview applies on demand", 1, 1)
        stat = self.source_path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self._source_stamp:
            raise ValueError("The source image changed during fitting. Reopen the experiment.")
        preview = RegistrationPreview(self.preview_key(settings, upstream, crop, upstream_crop),
                                      TunedRegistration(settings.model_copy(deep=True), signature, register, crop), preceding)
        self._previews[mode] = preview
        return preview

    def preview_frame(self, preview: RegistrationPreview, frame_index: int = 0,
                      channel: int | str = 0, z_index: int = 0) -> NDArray:
        """Apply fitted transforms to one requested plane, caching at most 8 / 64 MiB."""
        stat = self.source_path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self._source_stamp:
            raise ValueError("The source image changed. Reopen the experiment before previewing.")
        self._plane_selection(frame_index, channel, z_index)
        key = frame_index, self._resolve_channel(channel), z_index
        with self._preview_lock:
            if key in preview.planes:
                preview.planes.move_to_end(key)
                return preview.planes[key]
            source = (self.preview_frame(preview.upstream, *key) if preview.upstream is not None
                      else self.display_frame(*key))
            output = preview.result.register.apply_plane(source, frame=key[0], channel=key[1])
            output.setflags(write=False)
            if output.nbytes <= 64 * 1024**2:
                preview.planes[key] = output
                while len(preview.planes) > 8 or sum(plane.nbytes for plane in preview.planes.values()) > 64 * 1024**2:
                    preview.planes.popitem(last=False)
            return output

    def save_preview(self, preview: RegistrationPreview) -> Path:
        """Save accepted settings, fitting crop and transforms without processing the stack."""
        stat = self.source_path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self._source_stamp:
            raise ValueError("The source changed. Reopen and run a new preview before saving.")
        return save_tuning(self.source_path, preview.result)

    def close(self) -> None:
        """Release preview planes and original input caches."""
        self._previews.clear()
        super().close()
