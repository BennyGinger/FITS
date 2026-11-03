"""Read and cache model choices without loading model weights."""

from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version


@dataclass(frozen=True, slots=True)
class CellposeModelOptions:
    """
    Installed Cellpose backend and its available built-in models.
    """

    backend: str
    default_model: str
    built_in_models: tuple[str, ...]


def model_setting_path() -> str:
    """
    Select the settings field using package metadata without importing Cellpose.
    """
    return 'user_settings.model_type' if version('cellpose').split('.')[0] == '3' else 'user_settings.pretrained_model'


@lru_cache(maxsize=1)
def installed_model_options() -> CellposeModelOptions:
    """
    Discover authoritative choices once; defer expensive imports to the worker.
    """
    from cellpose_kit.backend.factory import load_backend

    backend, backend_name = load_backend()
    configured = backend.configure_model({}, do_denoise=False)
    default_model = configured.get('model_type') or configured.get('pretrained_model')
    if not isinstance(default_model, str):
        raise ValueError(f'Cellpose {backend_name} did not provide a default model.')
    models = tuple(dict.fromkeys([default_model, *backend.model_names]))
    return CellposeModelOptions(backend=backend_name, default_model=default_model, built_in_models=models)
