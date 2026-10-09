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

from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.tasks.registration.registration_resolver import resolve_registration_plan

Mode = Literal["time", "channel"]
RegistrationSettings = RegisterTimeSettings | RegisterChannelSettings
logger = logging.getLogger(__name__)
FORMAT_VERSION = 1


def tuning_path(source: Path, mode: Mode) -> Path:
    return source.parent / ".fits" / "registration" / f"{mode}.npz"


def fitting_signature(fitting: NDArray, shape: tuple[int, ...], axes: str,
                      labels: tuple[str, ...], settings: RegistrationSettings) -> str:
    """Hash only the projected planes used by fitting, one plane at a time."""
    canonical_axes = "".join(axis for axis in "TCZYX" if axis in axes)
    canonical_shape = tuple(shape[axes.index(axis)] for axis in canonical_axes)
    digest = sha256(json.dumps({"shape": canonical_shape, "axes": canonical_axes, "labels": labels,
                               "settings": settings.to_payload_dict()}, sort_keys=True).encode())
    for plane in fitting:
        digest.update(np.ascontiguousarray(plane, dtype=np.float32).tobytes())
    return digest.hexdigest()


@dataclass
class TunedRegistration:
    settings: RegistrationSettings
    signature: str
    register: RegisterModel


def load_tuning(source: Path, mode: Mode) -> TunedRegistration | None:
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
            model = TransformModel(mode, plan.method, stored["transform"], metadata["reference_channel"])
            register = RegisterModel(plan.backend).set_model(model)
            return TunedRegistration(settings, metadata["signature"], register)
    except (OSError, ValueError, KeyError, TypeError, EOFError, BadZipFile) as error:
        logger.warning("Ignoring unreadable registration tuning %s: %s", path, error)
        return None


def save_tuning(source: Path, result: TunedRegistration) -> Path:
    model = result.register.model
    path = tuning_path(source, model.mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"version": FORMAT_VERSION, "mode": model.mode,
                "backend": result.register.backend, "reference_channel": model.reference_channel,
                "settings": result.settings.to_payload_dict(), "signature": result.signature}
    temporary_path = None
    try:
        with NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            np.savez_compressed(temporary, transform=model.transform,
                                metadata=np.asarray(json.dumps(metadata, sort_keys=True)))
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def reusable_model(tuned: TunedRegistration | None, *, array: NDArray, axes: str,
                   labels: tuple[str, ...], settings: RegistrationSettings,
                   fit_channel: int | None = None,
                   reference_channel: int | None = None) -> RegisterModel | None:
    if tuned is None:
        return None
    if isinstance(settings, RegisterTimeSettings):
        preparation = FitPreparation.for_time(array, axes, fit_channel)
    else:
        preparation = FitPreparation.for_channel(array, axes, reference_channel, settings.reference_frame)
    assert preparation.fit_array is not None
    if len(tuned.register.model.transform) != len(preparation.fit_array):
        logger.warning("Saved registration transform count does not match the input; fitting again.")
        return None
    signature = fitting_signature(preparation.fit_array, array.shape, axes, labels, settings)
    if signature != tuned.signature:
        logger.info("Registration tuning input changed; fitting fresh transforms for %s.", tuned.register.model.mode)
        return None
    logger.info("Reusing tuned %s registration transforms.", tuned.register.model.mode)
    return tuned.register
