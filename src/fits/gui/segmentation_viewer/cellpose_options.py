from __future__ import annotations

from dataclasses import dataclass

from cellpose_kit.backend.factory import load_backend


@dataclass(frozen=True, slots=True)
class CellposeModelOptions:
    """
    Installed Cellpose backend and its available built-in models.
    """

    backend: str
    default_model: str
    built_in_models: tuple[str, ...]


def installed_model_options() -> CellposeModelOptions:
    """
    Read model choices and the default from the installed Cellpose backend.
    """
    backend, backend_name = load_backend()
    configured = backend.configure_model({}, do_denoise=False)
    default_model = configured.get("model_type") or configured.get("pretrained_model")
    if not isinstance(default_model, str):
        raise ValueError(f"Cellpose {backend_name} did not provide a default model.")
    models = tuple(dict.fromkeys([default_model, *backend.model_names]))
    return CellposeModelOptions(backend=backend_name,
                                default_model=default_model,
                                built_in_models=models,)
