"""FITS-owned accepted registration settings and reusable StackAlign models.

Reuse is based on fitting pixels, not paths/mtime: folders remain movable and
channel tuning remains valid after a matching time-registration pipeline step.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from zipfile import BadZipFile

import numpy as np
from numpy.typing import NDArray
from stackalign import RegisterModel, TransformModel
from stackalign.preparation import FitPreparation
from stackalign.planes import fit_planes
from stackalign.constants import Method

from fits.interaction.crop import CropBounds, validate_crop
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan

Mode = Literal["time", "channel"]
RegistrationSettings = RegisterTimeSettings | RegisterChannelSettings
logger = logging.getLogger(__name__)
FORMAT_VERSION = 1


def tuning_path(source: Path, mode: Mode) -> Path:
    """Locate accepted settings and transforms for one registration mode."""
    return source.parent / ".fits" / "registration" / f"{mode}.npz"


def fitting_signature(fitting: NDArray, shape: tuple[int, ...], axes: str,
                      labels: tuple[str, ...], settings: RegistrationSettings,
                      crop: CropBounds | None = None) -> str:
    """Hash only the projected planes used by fitting, one plane at a time."""
    canonical_axes = "".join(axis for axis in "TCZYX" if axis in axes)
    canonical_shape = tuple(shape[axes.index(axis)] for axis in canonical_axes)
    digest = sha256(json.dumps({"shape": canonical_shape, "axes": canonical_axes, "labels": labels,
                               "settings": settings.to_payload_dict()}, sort_keys=True).encode())
    if crop is not None:
        digest.update(json.dumps({"crop": crop}).encode())
    for plane in fitting:
        digest.update(np.ascontiguousarray(plane, dtype=np.float32).tobytes())
    return digest.hexdigest()


@dataclass
class TunedRegistration:
    settings: RegistrationSettings
    signature: str
    register: RegisterModel | None
    crop: CropBounds | None = None


def full_image_model(matrices: NDArray, *, backend: str, mode: Mode, method: Method,
                     reference_channel: int | None, crop: CropBounds | None) -> RegisterModel:
    """Lift crop-local transforms to full-image coordinates for every backend."""
    if crop is not None:
        origin = np.eye(3)
        origin[:2, 2] = crop[:2]
        inverse = np.eye(3)
        inverse[:2, 2] = -np.asarray(crop[:2])
        matrices = origin @ matrices @ inverse
    return RegisterModel(backend).set_model(TransformModel(mode, method, matrices, reference_channel))


def load_tuning(source: Path, mode: Mode) -> TunedRegistration | None:
    """Read accepted settings, fitting crop and any saved full-image transforms."""
    path = tuning_path(source, mode)
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as stored:
            metadata = json.loads(str(stored["metadata"].item()))
            if metadata["version"] != FORMAT_VERSION or metadata["mode"] != mode:
                raise ValueError("Unsupported registration tuning format.")
            settings_type = RegisterTimeSettings if mode == "time" else RegisterChannelSettings
            settings = settings_type.model_validate(metadata["settings"])
            plan = resolve_registration_plan(settings.context, settings.backend, settings.method)
            if plan.mode != mode or plan.backend != metadata["backend"]:
                raise ValueError("Registration model and settings disagree.")
            register = None
            if metadata.get("has_model", True):
                model = TransformModel(mode, plan.method, stored["transform"], metadata["reference_channel"])
                register = RegisterModel(plan.backend).set_model(model)
            crop = metadata.get("crop")
            if crop is not None:
                if not isinstance(crop, list) or len(crop) != 4:
                    raise ValueError("Invalid saved fitting crop.")
                crop = (crop[0], crop[1], crop[2], crop[3])
                validate_crop(crop, crop[2], crop[3])
            return TunedRegistration(settings, metadata["signature"], register, crop)
    except (OSError, ValueError, KeyError, TypeError, EOFError, BadZipFile) as error:
        logger.warning("Ignoring unreadable registration tuning %s: %s", path, error)
        return None


def save_tuning(source: Path, result: TunedRegistration) -> Path:
    """Atomically persist settings and crop, with transforms only when fitted."""
    model = result.register.model if result.register is not None else None
    plan = resolve_registration_plan(result.settings.context, result.settings.backend, result.settings.method)
    path = tuning_path(source, plan.mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"version": FORMAT_VERSION, "mode": plan.mode, "has_model": model is not None,
                "backend": plan.backend, "reference_channel": model.reference_channel if model is not None else None,
                "settings": result.settings.to_payload_dict(), "signature": result.signature,
                "crop": result.crop}
    temporary_path = None
    try:
        with NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            arrays = {"metadata": np.asarray(json.dumps(metadata, sort_keys=True))}
            if model is not None:
                arrays["transform"] = model.transform
            np.savez_compressed(temporary, **arrays)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def reusable_model(tuned: TunedRegistration | None, *, array: NDArray, axes: str,
                   labels: tuple[str, ...], settings: RegistrationSettings,
                   fit_channel: int | None = None,
                   reference_channel: int | None = None) -> RegisterModel | None:
    """Reuse matching transforms, or refit the accepted crop if its input changed."""
    if tuned is None or (tuned.register is None and tuned.crop is None):
        return None
    fitting_source = array
    if tuned.crop is not None:
        validate_crop(tuned.crop, array.shape[axes.index("X")], array.shape[axes.index("Y")])
        x0, y0, x1, y1 = tuned.crop
        selection = [slice(None)] * array.ndim
        selection[axes.index("X")] = slice(x0, x1)
        selection[axes.index("Y")] = slice(y0, y1)
        fitting_source = array[tuple(selection)]
    if isinstance(settings, RegisterTimeSettings):
        preparation = FitPreparation.for_time(fitting_source, axes, fit_channel)
    else:
        preparation = FitPreparation.for_channel(fitting_source, axes, reference_channel, settings.reference_frame)
    assert preparation.fit_array is not None
    if tuned.register is not None and len(tuned.register.model.transform) != len(preparation.fit_array) and tuned.crop is None:
        logger.warning("Saved registration transform count does not match the input; fitting again.")
        return None
    signature = fitting_signature(preparation.fit_array, array.shape, axes, labels, settings, tuned.crop)
    if tuned.register is None or signature != tuned.signature:
        logger.info("Fitting fresh registration transforms for accepted settings.")
        if tuned.crop is None:
            return None
        plan = resolve_registration_plan(settings.context, settings.backend, settings.method)
        reference = settings.reference_strategy if isinstance(settings, RegisterTimeSettings) else reference_channel
        if reference is None:
            raise ValueError("Choose a reference channel.")
        excluded = [labels.index(label) for label in (settings.exclude_channel or ())] if isinstance(settings, RegisterChannelSettings) else []
        matrices = fit_planes(preparation.fit_array, backend=plan.backend, method=plan.method,
                              reference=reference, excluded=excluded)
        return full_image_model(matrices, backend=plan.backend, mode=plan.mode, method=plan.method,
                                reference_channel=reference_channel, crop=tuned.crop)
    logger.info("Reusing tuned %s registration transforms.", tuned.register.model.mode)
    return tuned.register
